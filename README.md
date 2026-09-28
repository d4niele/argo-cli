# skdid — Argo DidUp da riga di comando

Piccola CLI Python per consultare da terminale voti, compiti, promemoria,
comunicazioni di bacheca, assenze e note disciplinari del registro
elettronico **Argo DidUp Famiglia**, senza passare dal browser o dall'app.

> ⚠️ **Disclaimer**: questo progetto non è affiliato con Argo Software e
> non usa API pubbliche/documentate. Si appoggia alla libreria di terze
> parti [`didupwrapper`](https://github.com/Rocciadura/didupAPI-wrapper),
> ottenuta per reverse engineering del traffico dell'app ufficiale.
> Può smettere di funzionare in qualunque momento se Argo cambia il
> backend. Usalo solo con le tue credenziali e sotto la tua responsabilità.

## Funzionalità

- **Compiti**: da oggi alla fine della settimana corrente (estesa alla
  settimana successiva se lanciato venerdì/sabato/domenica).
- **Voti**: ultimi 7 giorni.
- **Promemoria** dei docenti (verifiche/interrogazioni annotate) — opzionale.
- **Comunicazioni di bacheca** scuola-famiglia, con scadenza e stato
  "presa visione" — opzionale.
- **Assenze/ritardi/uscite anticipate** (default: ultimi 30 giorni) — opzionale.
- **Note disciplinari** (default: ultimi 30 giorni) — opzionale.
- Intervallo di date personalizzato (`--dal`/`--al`) per interrogare
  qualsiasi periodo, su tutte le sezioni.
- Ordinamento per giorno (default) o per materia/docente/categoria
  (`--per-materia`).
- Output testuale leggibile o JSON (`--json`) per script/automazioni.
- Le sezioni senza risultati vengono omesse dall'output testuale.

## Requisiti

- Python 3.10+
- Le credenziali dell'app DidUp Famiglia (codice scuola, utente, password)

## Installazione

```bash
git clone <url-di-questo-repo>
cd skdid
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Configurazione

Copia il file di esempio e inserisci le tue credenziali (le stesse che usi
nell'app DidUp Famiglia):

```bash
cp .env.example .env.local
```

```
DIDUP_SCUOLA=SC12345
DIDUP_USERNAME=nome.utente
DIDUP_PASSWORD=...
```

`argo_cli.py` carica automaticamente `.env.local` all'avvio.
Il file è già escluso dal versionamento via `.gitignore`: **non
committarlo mai** e non incollare la password in chat, issue o commit.

## Uso

```bash
.venv/bin/python argo_cli.py
```

Mostra compiti (settimana corrente) e voti (ultimi 7 giorni).

### Sezioni opzionali

| Flag | Contenuto | Intervallo di default |
|---|---|---|
| `--promemoria` | verifiche/interrogazioni annotate dai docenti | come i compiti |
| `--bacheca` | comunicazioni scuola-famiglia | come i compiti |
| `--assenze` | assenze, ritardi, uscite anticipate | ultimi 30 giorni |
| `--note` | note disciplinari | ultimi 30 giorni |

Combinabili tra loro:

```bash
.venv/bin/python argo_cli.py --promemoria --bacheca --assenze --note
```

### Intervallo di date personalizzato

```bash
.venv/bin/python argo_cli.py --dal 01-09-2026 --al 30-09-2026
```

`--dal` e `--al` vanno usati insieme, formato `DD-MM-YYYY`, e sovrascrivono
i default per tutte le sezioni attive.

### Ordinamento

Di default l'output è raggruppato **per giorno**. Per raggrupparlo invece
per materia (compiti/voti), docente (promemoria/note) o categoria
(bacheca/assenze):

```bash
.venv/bin/python argo_cli.py --per-materia
```

### Output JSON

```bash
.venv/bin/python argo_cli.py --json
```

Utile per script o automazioni: ogni sezione richiesta compare come chiave
(`compiti`, `voti`, `promemoria`, `bacheca`, `assenze`, `note`) con
`dal`/`al`, il conteggio e l'elenco delle materie/docenti/categorie
coinvolte, e `gruppi` con il dettaglio ordinato cronologicamente.

## Alias da shell (opzionale)

Per lanciarlo più velocemente, aggiungi in `~/.bash_aliases`:

```bash
alias didup='/percorso/assoluto/skdid/.venv/bin/python /percorso/assoluto/skdid/argo_cli.py'
```

Poi, da un nuovo terminale:

```bash
didup
didup --json
didup --dal 01-09-2026 --al 30-09-2026 --per-materia
```

