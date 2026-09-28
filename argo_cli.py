#!/usr/bin/env python3
"""CLI per consultare voti e compiti da Argo DidUp Famiglia.

Usa la libreria non ufficiale ``didupwrapper`` (reverse engineering delle
API usate dall'app ufficiale). Le credenziali vanno fornite tramite
variabili d'ambiente (vedi README.md), mai passate come argomento da riga
di comando per non finire nella history della shell.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from didupwrapper import DiDUPClientSync
from didupwrapper.exceptions import AuthError, DiDUPError

ENV_FILE = Path(__file__).parent / ".env.local"


def carica_env_locale() -> None:
    """Carica DIDUP_* da .env.local senza sovrascrivere variabili già impostate."""
    if not ENV_FILE.exists():
        return
    for riga in ENV_FILE.read_text().splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#") or "=" not in riga:
            continue
        chiave, _, valore = riga.partition("=")
        chiave = chiave.strip()
        valore = valore.strip().strip('"').strip("'")
        if chiave and valore and chiave not in os.environ:
            os.environ[chiave] = valore


def leggi_credenziali() -> tuple[str, str, str]:
    scuola = os.environ.get("DIDUP_SCUOLA")
    utente = os.environ.get("DIDUP_USERNAME")
    password = os.environ.get("DIDUP_PASSWORD")
    mancanti = [
        nome
        for nome, val in (
            ("DIDUP_SCUOLA", scuola),
            ("DIDUP_USERNAME", utente),
            ("DIDUP_PASSWORD", password),
        )
        if not val
    ]
    if mancanti:
        print(
            "Variabili d'ambiente mancanti: " + ", ".join(mancanti),
            file=sys.stderr,
        )
        print(
            "Imposta DIDUP_SCUOLA, DIDUP_USERNAME e DIDUP_PASSWORD "
            "(vedi README.md).",
            file=sys.stderr,
        )
        sys.exit(1)
    return scuola, utente, password  # type: ignore[return-value]


def parse_data(testo: str) -> date | None:
    """Converte una data dell'API (``YYYY-MM-DD``, eventualmente con orario) in ``date``."""
    if not testo:
        return None
    try:
        return date.fromisoformat(testo[:10])
    except ValueError:
        return None


def fmt(giorno: date) -> str:
    return giorno.strftime("%d-%m-%Y")


def range_compiti(oggi: date) -> tuple[date, date]:
    """Da oggi alla domenica di questa settimana; se oggi è ven/sab/dom
    si estende alla domenica della settimana successiva."""
    giorno_settimana = oggi.weekday()  # lunedì=0 ... domenica=6
    fine = oggi + timedelta(days=6 - giorno_settimana)
    if giorno_settimana >= 4:  # venerdì, sabato, domenica
        fine += timedelta(days=7)
    return oggi, fine


def range_voti(oggi: date) -> tuple[date, date]:
    """Ultimi 7 giorni, oggi incluso."""
    return oggi - timedelta(days=6), oggi


def range_ultimo_mese(oggi: date) -> tuple[date, date]:
    """Ultimi 30 giorni, oggi incluso (per assenze e note, meno legate al ritmo settimanale)."""
    return oggi - timedelta(days=29), oggi


def data_da_argomento(testo: str) -> date:
    try:
        return datetime.strptime(testo, "%d-%m-%Y").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"data non valida '{testo}': usa il formato DD-MM-YYYY"
        ) from exc


PLURALI = {"materia": "materie", "docente": "docenti", "categoria": "categorie"}


def costruisci_sezione(
    inizio: date,
    fine: date,
    voci: list[tuple[date, str, str]],
    per_gruppo: bool,
    campo: str = "materia",
) -> dict:
    """``campo`` è il nome (singolare) della seconda colonna di ``voci``
    (es. ``"materia"`` per compiti/voti, ``"docente"`` per i promemoria)."""
    chiave_plurale = PLURALI[campo]
    valori = sorted({v for _, v, _ in voci})

    if per_gruppo:
        per_valore: dict[str, list[tuple[date, str]]] = {}
        for giorno, valore, testo in voci:
            per_valore.setdefault(valore, []).append((giorno, testo))
        for lista in per_valore.values():
            lista.sort(key=lambda coppia: coppia[0])
        gruppi = [
            {
                "etichetta": valore,
                "voci": [
                    {"data": fmt(giorno), "testo": testo}
                    for giorno, testo in per_valore[valore]
                ],
            }
            for valore in valori
        ]
    else:
        per_giorno: dict[date, list[tuple[str, str]]] = {}
        for giorno, valore, testo in voci:
            per_giorno.setdefault(giorno, []).append((valore, testo))
        for lista in per_giorno.values():
            lista.sort(key=lambda coppia: coppia[0])
        gruppi = [
            {
                "etichetta": fmt(giorno),
                "voci": [
                    {campo: valore, "testo": testo}
                    for valore, testo in per_giorno[giorno]
                ],
            }
            for giorno in sorted(per_giorno)
        ]

    return {
        "dal": fmt(inizio),
        "al": fmt(fine),
        f"numero_{chiave_plurale}": len(valori),
        chiave_plurale: valori,
        "ordinamento": campo if per_gruppo else "giorno",
        "gruppi": gruppi,
    }


def stampa_sezione_testo(titolo: str, sezione: dict, campo: str = "materia") -> None:
    chiave_plurale = PLURALI[campo]
    valori = sezione[chiave_plurale]
    if not valori:
        return
    print(f"\n=== {titolo} (dal {sezione['dal']} al {sezione['al']}) ===")
    print(f"{sezione[f'numero_{chiave_plurale}']} {chiave_plurale} coinvolte: {', '.join(valori)}\n")
    for gruppo in sezione["gruppi"]:
        print(f"{gruppo['etichetta']}:")
        for voce in gruppo["voci"]:
            chiave_secondaria = voce.get("data") or voce.get(campo)
            print(f"  - {chiave_secondaria}: {voce['testo']}")
        print()


def raccogli_compiti(registro: list, inizio: date, fine: date) -> list[tuple[date, str, str]]:
    voci = []
    for lezione in registro:
        for compito in lezione.compiti:
            giorno = parse_data(compito.data_consegna)
            if giorno is not None and inizio <= giorno <= fine:
                voci.append((giorno, lezione.materia, compito.compito))
    return voci


def raccogli_voti(voti: list, inizio: date, fine: date) -> list[tuple[date, str, str]]:
    voci = []
    for v in voti:
        giorno = parse_data(v.dat_giorno)
        if giorno is None or not (inizio <= giorno <= fine):
            continue
        valore = v.valore if v.valore is not None else v.descrizione_voto
        testo = f"{valore}"
        if v.descrizione_prova:
            testo += f" ({v.descrizione_prova})"
        testo += f" — {v.docente}"
        if v.des_commento:
            testo += f" [{v.des_commento}]"
        voci.append((giorno, v.des_materia, testo))
    return voci


def raccogli_promemoria(promemoria: list, inizio: date, fine: date) -> list[tuple[date, str, str]]:
    voci = []
    for p in promemoria:
        if not p.flg_visibile_famiglia:
            continue
        giorno = parse_data(p.dat_giorno)
        if giorno is None or not (inizio <= giorno <= fine):
            continue
        testo = p.des_annotazioni
        if p.ora_inizio and p.ora_fine:
            testo += f" [{p.ora_inizio[:5]}-{p.ora_fine[:5]}]"
        voci.append((giorno, p.docente, testo))
    return voci


def raccogli_bacheca(bacheca: list, inizio: date, fine: date) -> list[tuple[date, str, str]]:
    voci = []
    for c in bacheca:
        giorno = parse_data(c.data)
        if giorno is None or not (inizio <= giorno <= fine):
            continue
        testo = c.messaggio
        if c.autore:
            testo += f" — {c.autore}"
        if c.data_scadenza:
            scadenza = parse_data(c.data_scadenza)
            if scadenza is not None:
                testo += f" (scadenza {fmt(scadenza)})"
        if c.pv_richiesta and not c.is_presa_visione:
            testo += " [presa visione richiesta]"
        voci.append((giorno, c.categoria or "Generale", testo))
    return voci


def raccogli_assenze(assenze: list, inizio: date, fine: date) -> list[tuple[date, str, str]]:
    voci = []
    for a in assenze:
        giorno = parse_data(a.data)
        if giorno is None or not (inizio <= giorno <= fine):
            continue
        testo = a.descrizione
        extra = []
        if a.da_giustificare:
            extra.append("da giustificare")
        elif a.giustificata:
            extra.append("giustificata")
        if a.nota:
            extra.append(a.nota)
        if extra:
            testo += " (" + "; ".join(extra) + ")"
        if a.docente:
            testo += f" — {a.docente}"
        voci.append((giorno, a.descrizione or "Evento", testo))
    return voci


def raccogli_note(note: list, inizio: date, fine: date) -> list[tuple[date, str, str]]:
    voci = []
    for n in note:
        giorno = parse_data(n.data)
        if giorno is None or not (inizio <= giorno <= fine):
            continue
        voci.append((giorno, n.docente, n.descrizione))
    return voci


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Consulta voti e compiti su Argo DidUp Famiglia."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Stampa il risultato come JSON invece che come testo leggibile.",
    )
    parser.add_argument(
        "--dal",
        type=data_da_argomento,
        metavar="DD-MM-YYYY",
        help="Inizio intervallo personalizzato per voti e compiti (richiede anche --al).",
    )
    parser.add_argument(
        "--al",
        type=data_da_argomento,
        metavar="DD-MM-YYYY",
        help="Fine intervallo personalizzato per voti e compiti (richiede anche --dal).",
    )
    parser.add_argument(
        "--per-materia",
        action="store_true",
        help="Raggruppa e ordina l'output per materia/docente invece che per giorno (default: per giorno).",
    )
    parser.add_argument(
        "--promemoria",
        action="store_true",
        help="Includi i promemoria dei docenti (es. verifiche/interrogazioni programmate).",
    )
    parser.add_argument(
        "--bacheca",
        action="store_true",
        help="Includi le comunicazioni di bacheca scuola-famiglia.",
    )
    parser.add_argument(
        "--assenze",
        action="store_true",
        help="Includi assenze, ritardi e uscite anticipate (default: ultimi 30 giorni).",
    )
    parser.add_argument(
        "--note",
        action="store_true",
        help="Includi le note disciplinari (default: ultimi 30 giorni).",
    )
    args = parser.parse_args()

    if bool(args.dal) != bool(args.al):
        parser.error("--dal e --al vanno usati insieme")
    if args.dal and args.al and args.dal > args.al:
        parser.error("--dal deve essere precedente o uguale a --al")

    carica_env_locale()
    scuola, utente, password = leggi_credenziali()

    try:
        with DiDUPClientSync(scuola, utente, password, auto_versione=True) as didup:
            voti = didup.get_voti()
            registro = didup.get_registro()
            promemoria = didup.get_promemoria() if args.promemoria else []
            bacheca = didup.get_bacheca() if args.bacheca else []
            assenze = didup.get_assenze() if args.assenze else []
            note = didup.get_note_disciplinari() if args.note else []
    except AuthError:
        print("Credenziali non valide o accesso rifiutato.", file=sys.stderr)
        sys.exit(1)
    except DiDUPError as exc:
        print(f"Errore nella comunicazione con Argo: {exc}", file=sys.stderr)
        sys.exit(1)

    oggi = date.today()

    if args.dal and args.al:
        inizio_settimanale, fine_settimanale = args.dal, args.al
        inizio_mensile, fine_mensile = args.dal, args.al
    else:
        inizio_settimanale, fine_settimanale = range_compiti(oggi)
        inizio_mensile, fine_mensile = range_ultimo_mese(oggi)

    inizio_voti, fine_voti = (args.dal, args.al) if (args.dal and args.al) else range_voti(oggi)

    sezioni: list[tuple[str, dict, str]] = []

    sezioni.append((
        "Compiti",
        costruisci_sezione(
            inizio_settimanale,
            fine_settimanale,
            raccogli_compiti(registro, inizio_settimanale, fine_settimanale),
            args.per_materia,
            "materia",
        ),
        "materia",
    ))
    sezioni.append((
        "Voti",
        costruisci_sezione(
            inizio_voti,
            fine_voti,
            raccogli_voti(voti, inizio_voti, fine_voti),
            args.per_materia,
            "materia",
        ),
        "materia",
    ))
    if args.promemoria:
        sezioni.append((
            "Promemoria",
            costruisci_sezione(
                inizio_settimanale,
                fine_settimanale,
                raccogli_promemoria(promemoria, inizio_settimanale, fine_settimanale),
                args.per_materia,
                "docente",
            ),
            "docente",
        ))
    if args.bacheca:
        sezioni.append((
            "Bacheca",
            costruisci_sezione(
                inizio_settimanale,
                fine_settimanale,
                raccogli_bacheca(bacheca, inizio_settimanale, fine_settimanale),
                args.per_materia,
                "categoria",
            ),
            "categoria",
        ))
    if args.assenze:
        sezioni.append((
            "Assenze/ritardi",
            costruisci_sezione(
                inizio_mensile,
                fine_mensile,
                raccogli_assenze(assenze, inizio_mensile, fine_mensile),
                args.per_materia,
                "categoria",
            ),
            "categoria",
        ))
    if args.note:
        sezioni.append((
            "Note disciplinari",
            costruisci_sezione(
                inizio_mensile,
                fine_mensile,
                raccogli_note(note, inizio_mensile, fine_mensile),
                args.per_materia,
                "docente",
            ),
            "docente",
        ))

    if args.json:
        chiave_json = {
            "Compiti": "compiti",
            "Voti": "voti",
            "Promemoria": "promemoria",
            "Bacheca": "bacheca",
            "Assenze/ritardi": "assenze",
            "Note disciplinari": "note",
        }
        print(
            json.dumps(
                {chiave_json[titolo]: sezione for titolo, sezione, _ in sezioni},
                ensure_ascii=False,
                indent=2,
            )
        )
    elif all(not sezione[PLURALI[campo]] for _, sezione, campo in sezioni):
        print("Nessun elemento trovato nell'intervallo richiesto.")
    else:
        for titolo, sezione, campo in sezioni:
            stampa_sezione_testo(titolo, sezione, campo)


if __name__ == "__main__":
    main()
