# argo-cli — Argo DidUp da riga di comando

Piccola CLI Python per consultare da terminale voti, compiti, promemoria,
comunicazioni di bacheca, assenze e note disciplinari del registro
elettronico **Argo DidUp Famiglia**, senza passare dal browser o dall'app.

> ⚠️ **Disclaimer**: questo progetto non è affiliato con Argo Software e
> non usa API pubbliche o documentate: Argo non ne offre per le famiglie.
> Replica le chiamate dell'app ufficiale DidUp Famiglia (reverse
> engineering del suo traffico, già noto da progetti come
> [`didupwrapper`](https://github.com/Rocciadura/didupAPI-wrapper)).
> Può smettere di funzionare in qualunque momento se Argo cambia il
> backend. Usalo solo con le tue credenziali e sotto la tua responsabilità.

## Funzionalità

- **Compiti**: da oggi alla fine della settimana corrente (estesa alla
  settimana successiva se lanciato venerdì/sabato/domenica).
- **Voti**: ultimi 7 giorni.
- **Promemoria** dei docenti (verifiche/interrogazioni annotate) — opzionale.
- **Comunicazioni di bacheca** scuola-famiglia, con scadenza e stato
  "presa visione" (default: ultimi 30 giorni, più quelle precedenti ancora
  in sospeso) — opzionale.
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

- Python 3.10+ (solo libreria standard, nessun pacchetto da installare)
- Le credenziali dell'app DidUp Famiglia (codice scuola, utente, password)

## Installazione

```bash
git clone <url-di-questo-repo>
cd argo-cli
```

Non ci sono dipendenze da installare: serve solo Python.

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
python3 argo_cli.py
```

Mostra compiti (settimana corrente) e voti (ultimi 7 giorni).

### Sezioni opzionali

| Flag | Contenuto | Intervallo di default |
|---|---|---|
| `--promemoria` / `--no-promemoria` | verifiche/interrogazioni annotate dai docenti (attivi di default, tranne con `--domani`) | da oggi ai prossimi 30 giorni |
| `--bacheca` | comunicazioni scuola-famiglia | pubblicate negli ultimi 30 giorni, più quelle precedenti con presa visione ancora da dare o scadenza non passata |
| `--assenze` | assenze, ritardi, uscite anticipate | ultimi 30 giorni |
| `--note` | note disciplinari | ultimi 30 giorni |

Combinabili tra loro:

```bash
python3 argo_cli.py --promemoria --bacheca --assenze --note
```

### Tutto in una volta

```bash
python3 argo_cli.py --all
```

Abilita tutte le sezioni opzionali (i promemoria si possono comunque escludere
con `--no-promemoria`) e aggiunge: **fuori classe**, **bacheca alunno**,
**periodi scolastici** (con media di scrutinio), **media generale** e **elenco docenti**.
Usa una sola chiamata API (`get_dashboard`), quindi è più veloce di attivare i flag singolarmente.
La bacheca alunno segue lo stesso intervallo della bacheca (ultimi 30 giorni,
più gli allegati precedenti ancora da scaricare).

Combinabile con `--json`, `--per-materia` e `--dal`/`--al`:

```bash
python3 argo_cli.py --all --json
python3 argo_cli.py --all --dal 01-09-2026 --al 30-09-2026
```

### Intervallo di date personalizzato

```bash
python3 argo_cli.py --dal 01-09-2026 --al 30-09-2026
```

`--dal` e `--al` vanno usati insieme, formato `DD-MM-YYYY`, e sovrascrivono
i default per tutte le sezioni attive. Con un intervallo esplicito la bacheca
mostra solo le comunicazioni pubblicate in quei giorni.

### Solo domani

```bash
python3 argo_cli.py --domani
```

Mostra solo i compiti da consegnare domani (nessun'altra sezione). Aggiungi
`--promemoria` per vedere anche i promemoria di domani.
Combinabile con `--json` e `--per-materia`; non con `--dal`/`--al`.

### Invio via WhatsApp

```bash
python3 argo_cli.py --domani --whatsapp
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

L'invio è considerato riuscito solo se CallMeBot conferma ("Message queued"):
se risponde con un errore (API key sbagliata, numero non attivato…) la CLI lo
stampa ed esce con codice 1, così un cron/timer se ne accorge. I messaggi più
lunghi di circa 1000 caratteri (tipico con `--all`) vengono spezzati in più
parti numerate `(1/3)`, `(2/3)`… inviate a qualche secondo di distanza.

### Più figli con lo stesso account

Con un account genitore collegato a più figli, Argo restituisce al login un
profilo per ciascun figlio. Senza opzioni la CLI usa il primo, quindi
mostra solo quel figlio. Per vedere gli alunni collegati:

```bash
python3 argo_cli.py --elenco-alunni
```

Per scegliere l'alunno (nome, nome e cognome o una sola parola del nominativo,
maiuscole indifferenti):

```bash
python3 argo_cli.py --alunno Mario --domani
```

In alternativa imposta `DIDUP_ALUNNO=Mario` in `.env.local`. Il nome scelto
viene stampato su stderr, così l'output (anche `--json`) resta pulito.

La scelta usa solo chiamate di lettura (`login` e `profilo`, le stesse che fa
l'app all'avvio).

### Ordinamento

Di default l'output è raggruppato **per giorno**. Per raggrupparlo invece
per materia (compiti/voti), docente (promemoria/note) o categoria
(bacheca/assenze):

```bash
python3 argo_cli.py --per-materia
```

### Output JSON

```bash
python3 argo_cli.py --json
```

Utile per script o automazioni: ogni sezione richiesta compare come chiave
(`compiti`, `voti`, `promemoria`, `bacheca`, `assenze`, `note`) con
`dal`/`al`, il conteggio e l'elenco delle materie/docenti/categorie
coinvolte, e `gruppi` con il dettaglio ordinato cronologicamente.

## Come funziona

Il client è in [`argo_api.py`](argo_api.py) e usa solo `urllib`. Replica le
stesse chiamate dell'app:

1. login OAuth2 con PKCE sul SSO di Argo (codice scuola, utente e password);
2. `login` applicativo, che restituisce un profilo per ogni alunno
   dell'account;
3. `dashboard/dashboard`, una sola richiesta che contiene voti, registro,
   promemoria, bacheca, assenze e note.

[`argo_cli.py`](argo_cli.py) filtra e raggruppa questi dati. Se Argo cambia
il flusso di login o i nomi dei campi, il codice da aggiornare è solo
`argo_api.py`.

## Test

```bash
python3 -m unittest discover -v
```

I test non richiedono un account Argo né la rete: verificano le funzioni che
filtrano e raggruppano i dati, e il client (`argo_api.py`) con le risposte di
Argo simulate. Una GitHub Action li esegue a ogni push e pull request.

## Alias da shell (opzionale)

Per lanciarlo più velocemente, aggiungi in `~/.bash_aliases`:

```bash
alias didup='python3 /percorso/assoluto/argo-cli/argo_cli.py'
```

Poi, da un nuovo terminale:

```bash
didup
didup --json
didup --dal 01-09-2026 --al 30-09-2026 --per-materia
```


## Licenza

Distribuito con licenza [MIT](LICENSE).
