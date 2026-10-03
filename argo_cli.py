#!/usr/bin/env python3
"""CLI per consultare voti e compiti da Argo DidUp Famiglia.

Usa la libreria non ufficiale ``didupwrapper`` (reverse engineering delle
API usate dall'app ufficiale). Le credenziali vanno fornite tramite
variabili d'ambiente (vedi README.md), mai passate come argomento da riga
di comando per non finire nella history della shell.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import secrets
import string
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from didupwrapper import DiDUPClientSync
from didupwrapper.exceptions import AuthError, DiDUPError

ENV_FILE = Path(__file__).parent / ".env.local"


def carica_env_locale() -> None:
    """Carica DIDUP_* da .env.local senza sovrascrivere variabili già impostate.

    Il file è letto sempre come UTF-8 (``utf-8-sig`` ignora l'eventuale BOM
    aggiunto da alcuni editor Windows), indipendentemente dalla codifica di
    sistema: altrimenti su Windows (cp1252) una password con lettere accentate
    verrebbe letta male e il login fallirebbe."""
    if not ENV_FILE.exists():
        return
    for riga in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
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


def invia_whatsapp(testo: str) -> None:
    """Invia ``testo`` via CallMeBot (https://www.callmebot.com/blog/free-api-whatsapp-messages/).

    ``CALLMEBOT_PHONE`` e ``CALLMEBOT_APIKEY`` possono contenere più valori
    separati da virgola (uno per destinatario, nello stesso ordine)."""
    telefoni = [t.strip() for t in os.environ.get("CALLMEBOT_PHONE", "").split(",") if t.strip()]
    apikeys = [k.strip() for k in os.environ.get("CALLMEBOT_APIKEY", "").split(",") if k.strip()]
    if not telefoni or not apikeys:
        print(
            "Per --whatsapp imposta CALLMEBOT_PHONE e CALLMEBOT_APIKEY (vedi README.md).",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(telefoni) != len(apikeys):
        print(
            "CALLMEBOT_PHONE e CALLMEBOT_APIKEY devono avere lo stesso numero di valori.",
            file=sys.stderr,
        )
        sys.exit(1)
    falliti = 0
    for telefono, apikey in zip(telefoni, apikeys):
        query = urllib.parse.urlencode({"phone": telefono, "text": testo, "apikey": apikey})
        try:
            with urllib.request.urlopen(
                f"https://api.callmebot.com/whatsapp.php?{query}", timeout=30
            ):
                pass
        except (urllib.error.URLError, OSError) as exc:
            print(f"Invio WhatsApp a {telefono} fallito: {exc}", file=sys.stderr)
            falliti += 1
        else:
            print(f"Messaggio WhatsApp inviato a {telefono}.", file=sys.stderr)
    if falliti:
        sys.exit(1)


def profili_account(didup: DiDUPClientSync) -> list[tuple[dict, dict]]:
    """Restituisce una coppia (dati di login, alunno) per ogni alunno dell'account.

    Con un account genitore e più figli il login applicativo (``POST login``)
    restituisce un profilo per figlio, ognuno con il suo ``token``
    (``x-auth-token``). didupwrapper 0.1.x tiene solo il primo (``data[0]``),
    quindi gli altri figli restano irraggiungibili. Qui si ripete la stessa
    chiamata ``login`` e, per ogni profilo, si legge il nome dell'alunno con
    ``GET profilo`` (``data.alunno``). Sono le stesse chiamate di sola lettura
    che fa l'app all'avvio.

    Usa attributi privati del wrapper: se una versione futura li cambia,
    l'errore viene segnalato in modo esplicito.
    """
    try:
        client = didup._async
        risposta = didup._run(
            client._post(
                "login",
                json={
                    "lista-opzioni-notifiche": "{}",
                    "lista-x-auth-token": "[]",
                    "clientID": "".join(
                        secrets.choice(string.ascii_letters + string.digits) for _ in range(163)
                    ),
                },
            )
        )
        client._verifica_success(risposta)
        profili = []
        for voce in (risposta or {}).get("data") or []:
            if voce.get("profiloDisabilitato"):
                continue
            client._login_data = voce
            dati = didup._run(client._get("profilo"))
            alunno = ((dati or {}).get("data") or {}).get("alunno") or {}
            profili.append((voce, alunno))
        return profili
    except AttributeError as exc:
        raise DiDUPError(
            f"versione di didupwrapper non supportata per la scelta dell'alunno ({exc})"
        ) from exc


def nome_alunno(alunno: dict) -> str:
    return alunno.get("nominativo") or f"{alunno.get('cognome', '')} {alunno.get('nome', '')}".strip()


def corrisponde(alunno: dict, cercato: str) -> bool:
    """Nome, nome e cognome in qualunque ordine o una sola parola del nominativo."""
    cercato = " ".join(cercato.split()).casefold()
    nome = alunno.get("nome", "").casefold()
    cognome = alunno.get("cognome", "").casefold()
    nominativo = " ".join(nome_alunno(alunno).split()).casefold()
    return bool(cercato) and (
        cercato in (nome, nominativo, f"{nome} {cognome}", f"{cognome} {nome}")
        or cercato in nominativo.split()
    )


def seleziona_alunno(didup: DiDUPClientSync, cercato: str) -> str:
    """Rende attivo il profilo dell'alunno ``cercato``; restituisce il suo nome."""
    profili = profili_account(didup)
    scelti = [(voce, alunno) for voce, alunno in profili if corrisponde(alunno, cercato)]
    if len(scelti) != 1:
        nomi = ", ".join(nome_alunno(a) for _, a in profili) or "nessuno"
        motivo = "nessun alunno" if not scelti else "più alunni"
        raise DiDUPError(f"{motivo} corrisponde a '{cercato}' (alunni dell'account: {nomi})")
    voce, alunno = scelti[0]
    didup._async._login_data = voce
    didup.invalida_cache()
    return nome_alunno(alunno)


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
        if p.ora_inizio and p.ora_fine and (p.ora_inizio[:5], p.ora_fine[:5]) != ("00:00", "00:00"):
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


def raccogli_fuori_classe(fuori_classe: list, inizio: date, fine: date) -> list[tuple[date, str, str]]:
    voci = []
    for f in fuori_classe:
        giorno = parse_data(f.data)
        if giorno is None or not (inizio <= giorno <= fine):
            continue
        testo = f.descrizione
        if f.nota:
            testo += f" ({f.nota})"
        if f.frequenza_on_line:
            testo += " [online]"
        voci.append((giorno, f.docente or "—", testo))
    return voci


def raccogli_bacheca_alunno(bacheca_alunno: list, inizio: date, fine: date) -> list[tuple[date, str, str]]:
    voci = []
    for f in bacheca_alunno:
        giorno = parse_data(f.data)
        if giorno is None or not (inizio <= giorno <= fine):
            continue
        testo = f.messaggio if f.messaggio else f.nome_file
        if f.flg_download_genitore and not f.is_presa_visione:
            testo += " [da scaricare]"
        voci.append((giorno, "Allegato", testo))
    return voci


def stampa_periodi(periodi: list, media_generale: float | None) -> None:
    if not periodi and media_generale is None:
        return
    print("\n=== Periodi scolastici ===")
    if media_generale is not None:
        print(f"Media generale: {media_generale:.2f}\n")
    for p in periodi:
        _di = parse_data(p.data_inizio)
        _df = parse_data(p.data_fine)
        inizio = fmt(_di) if _di else "?"
        fine = fmt(_df) if _df else "?"
        riga = f"  {p.descrizione} ({inizio} – {fine})"
        if p.media_scrutinio is not None:
            riga += f"  media scrutinio: {p.media_scrutinio:.2f}"
        print(riga)


def stampa_docenti(docenti: list) -> None:
    if not docenti:
        return
    print("\n=== Docenti ===")
    for d in sorted(docenti, key=lambda x: x.des_cognome):
        nome = f"{d.des_cognome} {d.des_nome}".strip()
        materie = ", ".join(d.materie) if d.materie else "—"
        riga = f"  {nome}  →  {materie}"
        if d.des_email:
            riga += f"  <{d.des_email}>"
        print(riga)


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
        "--domani",
        action="store_true",
        help="Mostra solo i compiti di domani (più i promemoria se usato con --promemoria). Non combinabile con --dal/--al.",
    )
    parser.add_argument(
        "--whatsapp",
        action="store_true",
        help="Invia l'output anche via WhatsApp (CallMeBot; vedi README.md).",
    )
    parser.add_argument(
        "--per-materia",
        action="store_true",
        help="Raggruppa e ordina l'output per materia/docente invece che per giorno (default: per giorno).",
    )
    parser.add_argument(
        "--promemoria",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Includi i promemoria dei docenti (es. verifiche/interrogazioni programmate). "
            "Attivo di default, tranne con --domani; usa --no-promemoria per escluderli."
        ),
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
    parser.add_argument(
        "--alunno",
        metavar="NOME",
        help=(
            "Per gli account genitore con più figli: nome dell'alunno da consultare "
            "(default: variabile DIDUP_ALUNNO, altrimenti il primo profilo)."
        ),
    )
    parser.add_argument(
        "--elenco-alunni",
        action="store_true",
        help="Elenca gli alunni collegati all'account ed esce.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Mostra tutto: compiti, voti, promemoria, bacheca, assenze, note, "
            "fuori classe, bacheca alunno, periodi, media e docenti. "
            "Usa una sola chiamata API (get_dashboard)."
        ),
    )
    args = parser.parse_args()

    promemoria_esplicito = bool(args.promemoria)
    if args.promemoria is None:
        # Nessuna scelta esplicita: attivi di default (anche con --all), non con --domani.
        args.promemoria = not args.domani

    if args.all:
        args.bacheca = True
        args.assenze = True
        args.note = True

    if args.domani:
        if args.dal or args.al:
            parser.error("--domani non è combinabile con --dal/--al")
        args.dal = args.al = date.today() + timedelta(days=1)
        args.all = args.bacheca = args.assenze = args.note = False
        args.promemoria = promemoria_esplicito

    if bool(args.dal) != bool(args.al):
        parser.error("--dal e --al vanno usati insieme")
    if args.dal and args.al and args.dal > args.al:
        parser.error("--dal deve essere precedente o uguale a --al")

    if args.whatsapp:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            esegui(args)
        testo = buffer.getvalue().strip()
        print(testo)
        invia_whatsapp(testo)
    else:
        esegui(args)


def esegui(args: argparse.Namespace) -> None:
    carica_env_locale()
    scuola, utente, password = leggi_credenziali()
    args.alunno = args.alunno or os.environ.get("DIDUP_ALUNNO")

    try:
        with DiDUPClientSync(scuola, utente, password, auto_versione=True) as didup:
            if args.elenco_alunni:
                for _, alunno in profili_account(didup):
                    print(nome_alunno(alunno))
                return
            if args.alunno:
                print(f"Alunno: {seleziona_alunno(didup, args.alunno)}", file=sys.stderr)
            if args.all:
                dashboard = didup.get_dashboard()
                voti = dashboard.voti
                registro = dashboard.registro
                promemoria = dashboard.promemoria
                bacheca = dashboard.bacheca
                assenze = dashboard.appello
                note = dashboard.note_disciplinari
                fuori_classe_raw = dashboard.fuori_classe
                bacheca_alunno_raw = dashboard.bacheca_alunno
                docenti_raw = dashboard.lista_docenti_classe
                periodi_raw = dashboard.lista_periodi
                media_generale = dashboard.media_generale
            else:
                voti = [] if args.domani else didup.get_voti()
                registro = didup.get_registro()
                promemoria = didup.get_promemoria() if args.promemoria else []
                bacheca = didup.get_bacheca() if args.bacheca else []
                assenze = didup.get_assenze() if args.assenze else []
                note = didup.get_note_disciplinari() if args.note else []
                fuori_classe_raw = []
                bacheca_alunno_raw = []
                docenti_raw = []
                periodi_raw = []
                media_generale = None
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

    if args.dal and args.al:
        inizio_prom, fine_prom = args.dal, args.al
    else:
        inizio_prom, fine_prom = oggi, oggi + timedelta(days=30)

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
    if not args.domani:
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
                inizio_prom,
                fine_prom,
                raccogli_promemoria(promemoria, inizio_prom, fine_prom),
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
    if fuori_classe_raw:
        sezioni.append((
            "Fuori classe",
            costruisci_sezione(
                inizio_mensile,
                fine_mensile,
                raccogli_fuori_classe(fuori_classe_raw, inizio_mensile, fine_mensile),
                args.per_materia,
                "docente",
            ),
            "docente",
        ))
    if bacheca_alunno_raw:
        sezioni.append((
            "Bacheca alunno",
            costruisci_sezione(
                inizio_settimanale,
                fine_settimanale,
                raccogli_bacheca_alunno(bacheca_alunno_raw, inizio_settimanale, fine_settimanale),
                args.per_materia,
                "categoria",
            ),
            "categoria",
        ))

    if args.json:
        chiave_json = {
            "Compiti": "compiti",
            "Voti": "voti",
            "Promemoria": "promemoria",
            "Bacheca": "bacheca",
            "Assenze/ritardi": "assenze",
            "Note disciplinari": "note",
            "Fuori classe": "fuori_classe",
            "Bacheca alunno": "bacheca_alunno",
        }
        output: dict = {chiave_json[titolo]: sezione for titolo, sezione, _ in sezioni}
        if media_generale is not None:
            output["media_generale"] = media_generale
        if periodi_raw:
            output["periodi"] = [
                {
                    "descrizione": p.descrizione,
                    "dal": fmt(_di) if (_di := parse_data(p.data_inizio)) else None,
                    "al": fmt(_df) if (_df := parse_data(p.data_fine)) else None,
                    "media_scrutinio": p.media_scrutinio,
                    "scrutinio_finale": p.is_scrutinio_finale,
                }
                for p in periodi_raw
            ]
        if docenti_raw:
            output["docenti"] = [
                {
                    "cognome": d.des_cognome,
                    "nome": d.des_nome,
                    "email": d.des_email or None,
                    "materie": d.materie,
                }
                for d in sorted(docenti_raw, key=lambda x: x.des_cognome)
            ]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif all(not sezione[PLURALI[campo]] for _, sezione, campo in sezioni):
        print("Nessun elemento trovato nell'intervallo richiesto.")
    else:
        for titolo, sezione, campo in sezioni:
            stampa_sezione_testo(titolo, sezione, campo)
        if periodi_raw or media_generale is not None:
            stampa_periodi(periodi_raw, media_generale)
        if docenti_raw:
            stampa_docenti(docenti_raw)


if __name__ == "__main__":
    main()
