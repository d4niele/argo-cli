# argo-cli — Argo DidUp da riga di comando

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
- **Account genitore con più figli**: scelta dell'alunno con `--alunno`
  (o `DIDUP_ALUNNO`), elenco con `--elenco-alunni`.
- Le sezioni senza risultati vengono omesse dall'output testuale.

## Requisiti

- Python 3.10+
- Le credenziali dell'app DidUp Famiglia (codice scuola, utente, password)

## Installazione

```bash
git clone <url-di-questo-repo>
cd argo-cli
```

Con **virtualenvwrapper** (consigliato):

```bash
mkvirtualenv argo
pip install -r requirements.txt
```

In alternativa con venv standard:

```bash
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
Il file va salvato in UTF-8 (default di quasi tutti gli editor) ed è già
escluso dal versionamento via `.gitignore`: **non
committarlo mai** e non incollare la password in chat, issue o commit.

## Uso

```bash
.venv/bin/python argo_cli.py
```

Mostra compiti (settimana corrente) e voti (ultimi 7 giorni).

### Sezioni opzionali

| Flag | Contenuto | Intervallo di default |
|---|---|---|
| `--promemoria` / `--no-promemoria` | verifiche/interrogazioni annotate dai docenti (attivi di default, tranne con `--domani`) | da oggi ai prossimi 30 giorni |
| `--bacheca` | comunicazioni scuola-famiglia | come i compiti |
| `--assenze` | assenze, ritardi, uscite anticipate | ultimi 30 giorni |
| `--note` | note disciplinari | ultimi 30 giorni |

Combinabili tra loro:

```bash
.venv/bin/python argo_cli.py --promemoria --bacheca --assenze --note
```

### Tutto in una volta

```bash
.venv/bin/python argo_cli.py --all
```

Abilita tutte le sezioni opzionali e aggiunge: **fuori classe**, **bacheca alunno**,
**periodi scolastici** (con media di scrutinio), **media generale** e **elenco docenti**.
Usa una sola chiamata API (`get_dashboard`), quindi è più veloce di attivare i flag singolarmente.

Combinabile con `--json`, `--per-materia` e `--dal`/`--al`:

```bash
.venv/bin/python argo_cli.py --all --json
.venv/bin/python argo_cli.py --all --dal 01-09-2026 --al 30-09-2026
```

### Intervallo di date personalizzato

```bash
.venv/bin/python argo_cli.py --dal 01-09-2026 --al 30-09-2026
```

`--dal` e `--al` vanno usati insieme, formato `DD-MM-YYYY`, e sovrascrivono
i default per tutte le sezioni attive.

### Solo domani

```bash
.venv/bin/python argo_cli.py --domani
```

Mostra solo i compiti da consegnare domani (nessun'altra sezione). Aggiungi
`--promemoria` per vedere anche i promemoria di domani.
Combinabile con `--json` e `--per-materia`; non con `--dal`/`--al`.

### Invio via WhatsApp

```bash
.venv/bin/python argo_cli.py --domani --whatsapp
```

Stampa l'output e lo invia anche via WhatsApp con [CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/)
(gratuito, per uso personale). Setup una tantum: aggiungi il contatto di
CallMeBot, inviagli il messaggio indicato sul loro sito per ottenere la
API key, poi aggiungi a `.env.local`:

```
CALLMEBOT_PHONE=+391234567890
CALLMEBOT_APIKEY=...
```

Per inviare a **più numeri** separa i valori con la virgola, nello stesso
ordine (ogni numero deve registrarsi a CallMeBot e ha la sua API key):

```
CALLMEBOT_PHONE=+391234567890,+399876543210
CALLMEBOT_APIKEY=chiave1,chiave2
```

Combinabile con qualsiasi altra opzione (usa il testo, non `--json`, se
vuoi un messaggio leggibile).

### Più figli con lo stesso account

Con un account genitore collegato a più figli, Argo restituisce al login un
profilo per ciascun figlio. `didupwrapper` (0.1.x) usa sempre il primo, quindi
senza opzioni la CLI mostra solo quel figlio. Per vedere gli alunni collegati:

```bash
.venv/bin/python argo_cli.py --elenco-alunni
```

Per scegliere l'alunno (nome, nome e cognome o una sola parola del nominativo,
maiuscole indifferenti):

```bash
.venv/bin/python argo_cli.py --alunno Mario --domani
```

In alternativa imposta `DIDUP_ALUNNO=Mario` in `.env.local`. Il nome scelto
viene stampato su stderr, così l'output (anche `--json`) resta pulito.

La scelta usa solo chiamate di lettura (`login` e `profilo`, le stesse che fa
l'app all'avvio) e alcuni attributi privati di `didupwrapper`: se una versione
futura li cambia, la CLI lo segnala con un errore esplicito.

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

## Test

```bash
.venv/bin/python -m unittest discover -v
```

I test non richiedono un account Argo: verificano le funzioni che filtrano e
raggruppano i dati usando i modelli veri di `didupwrapper`. La versione della
libreria è fissata in `requirements.txt` perché un suo aggiornamento potrebbe
rinominare i campi usati dalla CLI; per aggiornarla, cambia la versione e
controlla che i test passino. Una GitHub Action li esegue a ogni push e pull
request.

## Alias da shell (opzionale)

Per lanciarlo più velocemente, aggiungi in `~/.bash_aliases`:

Con **virtualenvwrapper**:

```bash
alias didup="$HOME/.virtualenvs/argo/bin/python $HOME/projects/argo-cli/argo_cli.py"
```

Con **venv standard**:

```bash
alias didup='/percorso/assoluto/argo-cli/.venv/bin/python /percorso/assoluto/argo-cli/argo_cli.py'
```

Poi, da un nuovo terminale:

```bash
didup
didup --json
didup --dal 01-09-2026 --al 30-09-2026 --per-materia
```

