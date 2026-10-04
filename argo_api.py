"""Client minimale per le API non ufficiali di Argo DidUp Famiglia.

Replica le chiamate fatte dall'app ufficiale (reverse engineering, nessuna
documentazione pubblica) usando solo la libreria standard:

1. ``GET  auth.portaleargo.it/oauth2/auth``    -> redirect con ``login_challenge``
2. ``POST www.portaleargo.it/auth/sso/login``  -> credenziali, redirect
3. catena di 3 redirect fino a ``?code=...``   (OAuth2 + PKCE S256)
4. ``POST auth.portaleargo.it/oauth2/token``   -> ``access_token``
5. ``POST appfamiglia/api/rest/login``         -> un profilo per alunno (``x-auth-token``)
6. ``POST appfamiglia/api/rest/dashboard/dashboard`` -> tutti i dati in una sola risposta

Se Argo cambia il flusso o i nomi dei campi, questo è l'unico modulo da aggiornare.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import string
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import MISSING, dataclass, field, fields
from datetime import datetime
from typing import Any, Callable

API_BASE_URL = "https://www.portaleargo.it/appfamiglia/api/rest/"
OAUTH_AUTH_URL = "https://auth.portaleargo.it/oauth2/auth"
OAUTH_TOKEN_URL = "https://auth.portaleargo.it/oauth2/token"
SSO_LOGIN_URL = "https://www.portaleargo.it/auth/sso/login"
CLIENT_ID = "72fd6dea-d0ab-4bb9-8eaa-3ac24c84886c"
REDIRECT_URI = "it.argosoft.didup.famiglia.new://login-callback"
SCOPES = ("openid", "offline", "profile", "user.roles", "argo")
APP_BUNDLE_ID = "it.argosoft.didup.famiglia.new"
APP_LOOKUP_URL = "https://itunes.apple.com/lookup"
VERSIONE_DEFAULT = "1.29.2"
DATA_INIZIO_DEFAULT = "2000-01-01 00:00:00.000"

_ALFABETO = string.ascii_letters + string.digits


class ArgoError(Exception):
    """Errore nella comunicazione con Argo."""


class ArgoAuthError(ArgoError):
    """Credenziali non valide o accesso rifiutato."""


# --------------------------------------------------------------------------- #
# Modelli                                                                      #
# --------------------------------------------------------------------------- #
# Solo i campi usati dalla CLI. I nomi seguono l'API (camelCase) convertiti in
# snake_case: ``datGiorno`` -> ``dat_giorno``. I campi mancanti o ``null``
# diventano il valore di default.


def _camel(nome: str) -> str:
    prima, *altre = nome.split("_")
    return prima + "".join(p.capitalize() for p in altre)


def _bool(v: Any) -> bool:
    """I flag arrivano come ``"S"``/``"N"`` oppure già come bool."""
    if isinstance(v, str):
        return v.strip().upper() in ("S", "SI", "TRUE", "1")
    return bool(v)


def _str(v: Any) -> str:
    return v.strip() if isinstance(v, str) else str(v)


def _float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _campo(default: Any = "", conv: Callable[[Any], Any] | None = None):
    return field(default=default, metadata={"conv": conv} if conv else {})


def _lista(modello: type) -> Any:
    return field(
        default_factory=list,
        metadata={"conv": lambda v: [modello.da_api(x) for x in v] if isinstance(v, list) else []},
    )


class Modello:
    @classmethod
    def da_api(cls, dati: Any):
        dati = dati if isinstance(dati, dict) else {}
        valori = {}
        for f in fields(cls):  # type: ignore[arg-type]
            grezzo = dati.get(_camel(f.name))
            if grezzo is None:
                continue
            conv = f.metadata.get("conv")
            if conv is None:
                tipo = type(f.default) if f.default is not MISSING else None
                conv = {str: _str, bool: _bool}.get(tipo)  # type: ignore[arg-type]
            valori[f.name] = conv(grezzo) if conv else grezzo
        return cls(**valori)  # type: ignore[call-arg]


@dataclass
class Compito(Modello):
    compito: str = ""
    data_consegna: str = ""


@dataclass
class Voto(Modello):
    dat_giorno: str = ""
    valore: float | None = _campo(None, _float)
    docente: str = ""
    des_materia: str = ""
    descrizione_prova: str = ""
    descrizione_voto: str = ""
    des_commento: str = ""


@dataclass
class EventoAppello(Modello):
    data: str = ""
    giustificata: str = ""  # "S" o "N"
    da_giustificare: bool = False
    docente: str = ""
    descrizione: str = ""
    nota: str | None = None

    @property
    def is_giustificata(self) -> bool:
        return self.giustificata.upper() == "S"


@dataclass
class RegistroLezione(Modello):
    materia: str = ""
    compiti: list[Compito] = _lista(Compito)


@dataclass
class NotaDisciplinare(Modello):
    data: str = ""
    docente: str = ""
    descrizione: str = ""


@dataclass
class Promemoria(Modello):
    dat_giorno: str = ""
    des_annotazioni: str = ""
    docente: str = ""
    ora_inizio: str = ""
    ora_fine: str = ""
    flg_visibile_famiglia: bool = True


@dataclass
class ComunicazioneBacheca(Modello):
    data: str = ""
    messaggio: str = ""
    autore: str = ""
    categoria: str = ""
    pv_richiesta: bool = False
    is_presa_visione: bool = False
    data_scadenza: str | None = None


@dataclass
class FileBachecaAlunno(Modello):
    data: str = ""
    nome_file: str = ""
    messaggio: str = ""
    flg_download_genitore: bool = False
    is_presa_visione: bool = False


@dataclass
class FuoriClasse(Modello):
    data: str = ""
    descrizione: str = ""
    docente: str = ""
    nota: str | None = None
    frequenza_on_line: bool = False


@dataclass
class Docente(Modello):
    des_nome: str = ""
    des_cognome: str = ""
    des_email: str = ""
    materie: list[str] = field(
        default_factory=list,
        metadata={"conv": lambda v: [str(m) for m in v] if isinstance(v, list) else []},
    )


@dataclass
class Periodo(Modello):
    descrizione: str = ""
    data_inizio: str = ""
    data_fine: str = ""
    media_scrutinio: float | None = _campo(None, _float)
    is_scrutinio_finale: bool = False


@dataclass
class Dashboard(Modello):
    media_generale: float | None = _campo(None, _float)
    voti: list[Voto] = _lista(Voto)
    appello: list[EventoAppello] = _lista(EventoAppello)
    registro: list[RegistroLezione] = _lista(RegistroLezione)
    note_disciplinari: list[NotaDisciplinare] = _lista(NotaDisciplinare)
    promemoria: list[Promemoria] = _lista(Promemoria)
    bacheca: list[ComunicazioneBacheca] = _lista(ComunicazioneBacheca)
    bacheca_alunno: list[FileBachecaAlunno] = _lista(FileBachecaAlunno)
    fuori_classe: list[FuoriClasse] = _lista(FuoriClasse)
    lista_docenti_classe: list[Docente] = _lista(Docente)
    lista_periodi: list[Periodo] = _lista(Periodo)


@dataclass
class Profilo:
    """Un alunno dell'account: ``voce`` è la risposta di ``login`` (con il suo
    ``token``), ``alunno`` i dati anagrafici letti da ``profilo``."""

    voce: dict
    alunno: dict


def estrai_dashboard(risposta: Any) -> Any:
    """Normalizza l'incapsulamento ``{"data": {"dati": [ {...} ]}}`` di Argo."""
    if not isinstance(risposta, dict):
        return risposta
    contenuto = risposta.get("data", risposta)
    if isinstance(contenuto, dict) and "dati" in contenuto:
        dati = contenuto["dati"]
        return dati[0] if isinstance(dati, list) and dati else dati
    return contenuto


# --------------------------------------------------------------------------- #
# HTTP                                                                         #
# --------------------------------------------------------------------------- #
class _SenzaRedirect(urllib.request.HTTPRedirectHandler):
    """Non segue i redirect: urllib solleva ``HTTPError`` e leggiamo ``Location``."""

    def redirect_request(self, *args, **kwargs):  # type: ignore[override]
        return None


# Niente HTTPCookieProcessor: i cookie del flusso SSO si gestiscono a mano.
_opener = urllib.request.build_opener(_SenzaRedirect)


def _richiesta(
    metodo: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    corpo: bytes | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any, bytes]:
    """Esegue una richiesta senza seguire i redirect; restituisce (stato, header, corpo).

    Gli stati 4xx/5xx non sollevano: li interpreta il chiamante."""
    req = urllib.request.Request(url, data=corpo, headers=headers or {}, method=metodo)
    try:
        with _opener.open(req, timeout=timeout) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.headers, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ArgoError(f"connessione ad Argo non riuscita ({exc})") from exc


def _json(corpo: bytes) -> Any:
    if not corpo:
        return None
    try:
        return json.loads(corpo)
    except ValueError:
        return None


def _messaggio(payload: Any, stato: int) -> str:
    if isinstance(payload, dict):
        for chiave in ("msg", "message", "error_description", "error", "errore", "messaggio"):
            valore = payload.get(chiave)
            if isinstance(valore, str) and valore.strip():
                return valore
    return f"richiesta fallita (HTTP {stato})"


def _errore(stato: int, payload: Any) -> ArgoError:
    classe = ArgoAuthError if stato in (401, 403) else ArgoError
    return classe(f"{_messaggio(payload, stato)} (HTTP {stato})")


def _casuale(lunghezza: int) -> str:
    return "".join(secrets.choice(_ALFABETO) for _ in range(lunghezza))


def _challenge_pkce(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _param(url: str, nome: str) -> str | None:
    valori = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get(nome)
    return valori[0] if valori else None


def _cookie(headers: Any) -> list[str]:
    return [h.split(";", 1)[0].strip() for h in headers.get_all("Set-Cookie") or [] if h.strip()]


def formatta_data(dt: datetime) -> str:
    """Formato dell'API: ``YYYY-MM-DD HH:MM:SS.mmm``."""
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def recupera_versione_app(timeout: float = 15.0) -> str | None:
    """Ultima versione dell'app sull'App Store, per l'header ``argo-client-version``."""
    url = APP_LOOKUP_URL + "?" + urllib.parse.urlencode({"bundleId": APP_BUNDLE_ID})
    try:
        stato, _, corpo = _richiesta("GET", url, timeout=timeout)
        risultati = (_json(corpo) or {}).get("results") or []
        return risultati[0].get("version") if stato == 200 and risultati else None
    except (ArgoError, AttributeError, IndexError):
        return None


# --------------------------------------------------------------------------- #
# Client                                                                       #
# --------------------------------------------------------------------------- #
class ArgoClient:
    def __init__(
        self,
        scuola: str,
        utente: str,
        password: str,
        *,
        versione: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._scuola = scuola
        self._utente = utente
        self._password = password
        self._versione = versione
        self._timeout = timeout
        self._token: str | None = None
        self._scade_il: float | None = None
        self._voci: list[dict] = []

    # -- autenticazione ---------------------------------------------------- #
    def login(self) -> None:
        """OAuth2/PKCE + login applicativo."""
        if self._versione is None:
            self._versione = recupera_versione_app() or VERSIONE_DEFAULT
        verifier = _casuale(43)
        code = self._ottieni_code(verifier)
        self._scambia_code(code, verifier)
        self._voci = self._login_applicativo()

    def _ottieni_code(self, verifier: str) -> str:
        """Percorre la catena di redirect del SSO fino al ``code``."""
        state, nonce = _casuale(22), _casuale(22)
        q = urllib.parse.quote
        url_auth = (
            f"{OAUTH_AUTH_URL}?redirect_uri={q(REDIRECT_URI, safe='')}"
            f"&client_id={CLIENT_ID}&response_type=code&prompt=login"
            f"&state={state}&nonce={nonce}&scope={q(' '.join(SCOPES), safe='')}"
            f"&code_challenge={_challenge_pkce(verifier)}&code_challenge_method=S256"
        )
        cookies: list[str] = []
        t = self._timeout

        # 1) Avvio OAuth -> redirect alla pagina di login con ``login_challenge``.
        stato, h, _ = _richiesta("GET", url_auth, timeout=t)
        cookies += _cookie(h)
        loc = h.get("Location")
        if not loc:
            raise ArgoError(f"avvio OAuth: redirect mancante (HTTP {stato})")
        challenge = _param(loc, "login_challenge")
        if not challenge:
            raise ArgoError("avvio OAuth: 'login_challenge' non trovato")

        # 2) Credenziali al SSO.
        corpo = urllib.parse.urlencode(
            {
                "challenge": challenge,
                "client_id": CLIENT_ID,
                "prefill": "false",
                "famiglia_customer_code": self._scuola,
                "username": self._utente,
                "password": self._password,
                "login": "true",
            },
            quote_via=urllib.parse.quote,
        ).encode()
        stato, h, _ = _richiesta(
            "POST",
            SSO_LOGIN_URL,
            headers={"content-type": "application/x-www-form-urlencoded"},
            corpo=corpo,
            timeout=t,
        )
        url1 = h.get("Location")
        if not url1:
            raise ArgoAuthError(
                f"login SSO fallito: credenziali errate o flusso cambiato (HTTP {stato})"
            )

        # 3) Redirect post-login (il secondo passo non invia cookie, come l'app).
        def passo(url: str, cookie: bool, nome: str) -> str:
            headers = {"cookie": "; ".join(cookies)} if cookie else {}
            _, h, _ = _richiesta("GET", url, headers=headers, timeout=t)
            if cookie:
                cookies.extend(_cookie(h))
            prossimo = h.get("Location")
            if not prossimo:
                raise ArgoError(f"catena OAuth interrotta ({nome})")
            return urllib.parse.urljoin(url, prossimo)

        url2 = passo(url1, True, "redirect 2")
        url3 = passo(url2, False, "redirect 3")
        url4 = passo(url3, True, "redirect finale")

        code = _param(url4, "code")
        if not code:
            raise ArgoError("code non presente nel redirect finale")
        return code

    def _scambia_code(self, code: str, verifier: str) -> None:
        corpo = urllib.parse.urlencode(
            {
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
                "client_id": CLIENT_ID,
            }
        ).encode()
        stato, _, raw = _richiesta(
            "POST",
            OAUTH_TOKEN_URL,
            headers={"content-type": "application/x-www-form-urlencoded"},
            corpo=corpo,
            timeout=self._timeout,
        )
        dati = _json(raw)
        if stato >= 400 or not isinstance(dati, dict) or "error" in dati:
            raise _errore(stato if stato >= 400 else 401, dati)
        self._token = dati.get("access_token")
        if not self._token:
            raise ArgoAuthError("token non presente nella risposta OAuth")
        scadenza = dati.get("expires_in")
        self._scade_il = time.time() + float(scadenza) if scadenza else None

    def _login_applicativo(self) -> list[dict]:
        risposta = self._api(
            "POST",
            "login",
            {
                "lista-opzioni-notifiche": "{}",
                "lista-x-auth-token": "[]",
                "clientID": _casuale(163),
            },
        )
        voci = (risposta or {}).get("data") or []
        if not voci:
            raise ArgoError("login applicativo: nessun profilo restituito")
        return voci

    # -- richieste API ----------------------------------------------------- #
    def _headers(self, voce: dict | None) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "argo-client-version": self._versione or VERSIONE_DEFAULT,
            "content-type": "application/json; charset=utf-8",
        }
        if self._token:
            headers["authorization"] = f"Bearer {self._token}"
            if self._scade_il is not None:
                headers["x-date-exp-auth"] = formatta_data(datetime.fromtimestamp(self._scade_il))
        if voce:
            if voce.get("token"):
                headers["x-auth-token"] = voce["token"]
            if voce.get("codMin"):
                headers["x-cod-min"] = voce["codMin"]
        return headers

    def _api(self, metodo: str, percorso: str, corpo: Any = None, voce: dict | None = None) -> Any:
        stato, _, raw = _richiesta(
            metodo,
            API_BASE_URL + percorso,
            headers=self._headers(voce),
            corpo=json.dumps(corpo).encode() if corpo is not None else None,
            timeout=self._timeout,
        )
        dati = _json(raw)
        if stato >= 400:
            raise _errore(stato, dati)
        if isinstance(dati, dict) and dati.get("success") is False:
            raise ArgoError(dati.get("msg") or "richiesta non riuscita")
        return dati

    # -- dati -------------------------------------------------------------- #
    def profili(self) -> list[Profilo]:
        """Un profilo per ogni alunno dell'account (i disabilitati sono esclusi).

        Con un account genitore e più figli ``login`` restituisce una voce per
        figlio, ognuna col suo ``token``; il nome si legge con ``GET profilo``."""
        profili = []
        for voce in self._voci:
            if voce.get("profiloDisabilitato"):
                continue
            dati = self._api("GET", "profilo", voce=voce)
            alunno = ((dati or {}).get("data") or {}).get("alunno") or {}
            profili.append(Profilo(voce, alunno))
        return profili

    def dashboard(self, voce: dict | None = None) -> Dashboard:
        """Tutti i dati dell'alunno (il primo dell'account se ``voce`` è omesso)."""
        voce = voce or self._voci[0]
        opzioni = {o["chiave"]: o["valore"] for o in voce.get("opzioni") or [] if "chiave" in o}
        risposta = self._api(
            "POST",
            "dashboard/dashboard",
            {
                "dataultimoaggiornamento": DATA_INIZIO_DEFAULT,
                "opzioni": json.dumps(opzioni, separators=(",", ":")),
            },
            voce=voce,
        )
        return Dashboard.da_api(estrai_dashboard(risposta))
