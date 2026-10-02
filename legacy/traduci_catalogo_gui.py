"""
Traduzione catalogo prodotti — versione con cache persistente e protezione codici.

NOVITA' rispetto alla versione precedente:
- CACHE PERSISTENTE cross-run (tabella SQLite cache_traduzioni): ogni testo
  già tradotto una volta (per una lingua) non viene MAI ritradotto, nemmeno
  in run futuri. Questo da solo rende gratuita la ripetizione di celle
  identiche tra prodotti diversi (varianti con stesso nome/descrizione).
- LEGENDA RICORRENZE (legenda_ricorrenze.json): alla primissima esecuzione,
  PRIMA di tradurre, analizza tutte le celle del foglio 'it' colonna per
  colonna, conta i valori che si ripetono identici, e salva un report.
  Le esecuzioni successive saltano questa analisi (il file esiste già).
  E' un report/diagnostica; il risparmio vero e proprio lo fa comunque
  la cache persistente sopra, che funziona indipendentemente da questo file.
- GUARDIA "uguale all'italiano": se una cella e' gia' valorizzata ma il suo
  contenuto e' IDENTICO al valore italiano corrispondente, viene considerata
  sospetta (probabile mancata traduzione) e viene ritentata.
- PROTEZIONE CODICI/NUMERI: prima di mandare qualunque testo a LibreTranslate,
  ogni token con cifre (codici prodotto, modelli, quantita' con unita' di
  misura) viene sostituito con un tag HTML vuoto <span id="kN"></span>,
  che il traduttore non altera. Dopo la traduzione, il codice originale
  viene rimesso al suo posto, byte per byte. La chiamata a LibreTranslate
  usa sempre format="html" (anche per campi senza HTML reale) per permettere
  a questi tag-segnaposto di sopravvivere intatti.
- CAMPI:
    nome             -> tradotto via API (protetto), avviso se >80 caratteri
    riepilogo        -> NON tradotto via API: riconosciuto come template
                        <p><strong>Etichetta: </strong>Valore</p>, etichette
                        e valori tradotti una volta sola (cache), poi
                        ricostruito. Se la struttura non corrisponde al
                        template atteso, segnala ed effettua comunque una
                        traduzione HTML protetta come fallback.
    descrizione      -> tradotto via API, HTML reale mantenuto e protetto
    metatitolo       -> tradotto via API (protetto)
    metadescrizione  -> tradotto via API (protetto)
    tag              -> letto dal sorgente SEPARATO DA VIRGOLA, ogni tag
                        tradotto singolarmente (protetto), poi ricomposto
                        separato da "$"
    url_rewritten    -> NON tradotto: generato deterministicamente dal nome
                        gia' tradotto con una funzione slug equivalente a
                        Tools::str2url() di PrestaShop. E' una ANTEPRIMA:
                        la versione definitiva/deduplicata contro il DB la
                        genera lo script PHP di import in produzione.

DIPENDENZA NUOVA: pip install unidecode

ARCHITETTURA DI BASE (INVARIATA):
- Ogni lingua gira su un thread dedicato, ciclo SEQUENZIALE riga per riga.
- Un limite GLOBALE (semaforo) di richieste concorrenti verso LibreTranslate,
  condiviso da tutte le lingue.
- Stato di avanzamento in SQLite (traduzioni_progress.db): commit ogni
  BATCH_SIZE righe, crash-safe.
- L'EXPORT su Excel e' un thread INDIPENDENTE, snapshot periodico, non
  blocca mai la traduzione.
- "sku" non viene mai tradotto. Corrispondenza tra fogli sempre per sku.

USO:
    python traduci_catalogo_gui.py                     # tutte le lingue
    python traduci_catalogo_gui.py en fr                # solo queste lingue
    python traduci_catalogo_gui.py en --limit=50         # solo le prime 50 righe (test)

IMPORTANTE — prima di lanciare, riavvia LibreTranslate SENZA log verboso
sul terminale interattivo:

    wsl
    source ~/libretranslate-env/bin/activate
    export CUDA_VISIBLE_DEVICES=2
    export ARGOS_DEVICE_TYPE=cuda
    libretranslate --host 0.0.0.0 --threads 8 \\
        --load-only it,en,fr,es,de,pt,pl,ro \\
        > ~/libretranslate.log 2>&1 &
"""

import os
import re
import sys
import json
import time
import traceback
import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

import requests
from openpyxl import load_workbook, Workbook

try:
    from unidecode import unidecode
except ImportError:
    unidecode = None  # genera_slug degrada ad ascii-only senza trascrizione accenti

# ------------------------- CONFIGURAZIONE -------------------------

CARTELLA_LAVORO = os.path.join(os.path.expanduser("~"), "Downloads")
FILE_PATH = os.path.join(CARTELLA_LAVORO, "traduzioni.xlsx")
DB_PATH = os.path.join(CARTELLA_LAVORO, "traduzioni_progress.db")
LEGENDA_PATH = os.path.join(CARTELLA_LAVORO, "legenda_ricorrenze.json")

SHEET_ORIGINE = "it"
TUTTE_LE_LINGUE = ["en", "fr", "es", "de", "pt", "pl", "ro"]  # usate SEMPRE per scansione+export


def _analizza_argomenti():
    """Argomenti CLI: lingue da tradurre (default: tutte) e opzionale
    --limit=N per elaborare solo le prime N righe (test rapido)."""
    limite = None
    lingue_richieste = []
    for a in sys.argv[1:]:
        a = a.strip()
        if a.lower().startswith("--limit="):
            try:
                limite = int(a.split("=", 1)[1])
                if limite <= 0:
                    raise ValueError
            except ValueError:
                print(f"Valore di --limit non valido: {a}")
                sys.exit(1)
        else:
            lingue_richieste.append(a.lower())

    if lingue_richieste:
        non_valide = [a for a in lingue_richieste if a not in TUTTE_LE_LINGUE]
        if non_valide:
            print(f"Lingue non valide: {non_valide}. Valide: {TUTTE_LE_LINGUE}")
            sys.exit(1)
        lingue = lingue_richieste
    else:
        lingue = list(TUTTE_LE_LINGUE)

    return lingue, limite


LINGUE_DESTINAZIONE, LIMITE_RIGHE = _analizza_argomenti()

LIBRETRANSLATE_URL = os.environ.get("LIBRETRANSLATE_URL", "http://localhost:5000/translate")
SOURCE_LANG = "it"
REQUEST_TIMEOUT = 60

COLONNA_SKU = "sku"
COLONNA_TAG = "tag"
COLONNA_URL = "url_rewritten"
SEPARATORE_TAG_OUTPUT = "$"

# colonne che passano per il ciclo di traduzione riga-per-riga (in quest'ordine)
COLONNE_LOOP = ["nome", "riepilogo", "descrizione", "metatitolo", "metadescrizione", "tag"]
# tutte le colonne salvate/esportate (loop + url_rewritten, calcolato a parte)
COLONNE_DA_TRADURRE = COLONNE_LOOP + [COLONNA_URL]
COLONNE_ATTESE = [COLONNA_SKU] + COLONNE_DA_TRADURRE

LUNGHEZZA_MAX_NOME = 80

BATCH_SIZE = 10
EXPORT_INTERVALLO_SECONDI = 300

MAX_RICHIESTE_CONCORRENTI = 7
_semaforo_richieste = threading.Semaphore(MAX_RICHIESTE_CONCORRENTI)

# --------------------------------------------------------------------

_cache_lock = threading.Lock()
_cache_traduzioni = {}          # (testo_protetto, lingua) -> traduzione, precaricata da SQLite
_cache_db_lock = threading.Lock()
_db_lock = threading.Lock()

log_queue = queue.Queue()
stato_lingue = {}
_stato_lock = threading.Lock()
stop_event = threading.Event()

FALLIMENTO = object()
ultimo_export = {"quando": None, "stato": "non ancora eseguito"}


def log(msg):
    ts = time.strftime("%H:%M:%S")
    log_queue.put(f"[{ts}] {msg}")


# ------------------------- UTILITY TESTO -------------------------

def e_vuoto(valore):
    return valore is None or str(valore).strip() == ""


def e_tutto_maiuscolo(testo):
    lettere = [c for c in testo if c.isalpha()]
    return len(lettere) > 0 and all(c.isupper() for c in lettere)


def _uguale_a_sorgente(valore_attuale, valore_sorgente):
    """True se una cella gia' tradotta e' identica (a meno di spazi) al
    valore italiano corrispondente: sospetto di mancata traduzione."""
    return str(valore_attuale).strip() == str(valore_sorgente).strip()


def _sembra_incompleta(sorgente, risultato):
    """Euristica difensiva: riconosce una traduzione troncata o mai avvenuta
    (bug osservato: il traduttore a volte restituisce solo un pezzo iniziale
    del testo, ancora in italiano, quando il payload ha una certa forma).
    Si applica sia a un risultato appena ricevuto sia a uno gia' salvato."""
    s = str(sorgente).strip()
    r = str(risultato).strip()
    if r == "":
        return True
    # il risultato e' un prefisso letterale (non tradotto) del sorgente
    if len(s) > 15 and len(r) < len(s) and s.lower().startswith(r.lower()):
        return True
    # troncamento grossolano: il risultato e' molto piu' corto del sorgente
    if len(s) > 20 and len(r) < len(s) * 0.5:
        return True
    return False


def _risultato_sospetto(sorgente, valore):
    """Unico punto di verità per 'questo valore è affidabile?' — usato sia
    per una cella già presente da un run precedente, sia per un risultato
    appena arrivato dal traduttore in questo stesso giro. Un risultato
    sospetto non viene MAI scritto, in nessuno dei due casi."""
    return _uguale_a_sorgente(valore, sorgente) or _sembra_incompleta(sorgente, valore)


# ------------------------- PROTEZIONE TAG E CODICI/NUMERI -------------------------
# Il traduttore non vede MAI un tag HTML ne' un codice/numero: vengono
# tenuti fuori dalla richiesta fin dall'inizio, non inseriti come
# segnaposto da recuperare dopo (tecnica rivelatasi inaffidabile: un
# segnaposto puo' essere spezzato dal tokenizzatore, o l'allineamento
# HTML del traduttore puo' troncare/corrompere il resto della stringa).

_TAG_SPLIT = re.compile(r'(<[^>]+>)')

_PROTECT_PATTERN = re.compile(r'''
    \d+(?:[.,]\d+)?\s?(?:mAh|mA|kWh|Wh|kg|mg|g|km|cm|mm|m|ml|l|V|A|W|Hz|GB|TB|MB)\b
    |
    \d+\s?x\b
    |
    \b[\w]*\d[\w-]*\b
''', re.VERBOSE | re.IGNORECASE)


def _dividi_per_tag(testo):
    """Divide una stringa in pezzi alternati ('tag', letterale) / ('testo',
    da elaborare). Se non ci sono tag reali, c'e' un solo pezzo 'testo'.
    I tag (compresi i loro attributi, es. style="color:#000000") non
    vengono MAI analizzati per codici/numeri: restano intatti."""
    pezzi = []
    for frammento in _TAG_SPLIT.split(testo):
        if frammento == "":
            continue
        if frammento.startswith("<") and frammento.endswith(">"):
            pezzi.append(("tag", frammento))
        else:
            pezzi.append(("testo", frammento))
    return pezzi


def _dividi_codici(testo):
    """Divide un pezzo di solo testo (nessun tag) in frammenti alternati
    ('testo', da tradurre) / ('codice', da lasciare letterale: codici
    prodotto, modelli, quantita' con unita' di misura)."""
    pezzi = []
    ultimo = 0
    for m in _PROTECT_PATTERN.finditer(testo):
        if m.start() > ultimo:
            pezzi.append(("testo", testo[ultimo:m.start()]))
        pezzi.append(("codice", m.group(0)))
        ultimo = m.end()
    if ultimo < len(testo):
        pezzi.append(("testo", testo[ultimo:]))
    return pezzi


# ------------------------- SLUG (anteprima, non definitivo) -------------------------

def genera_slug(testo):
    """Approssimazione di Tools::str2url() del core PrestaShop. E' una
    ANTEPRIMA: la versione definitiva e deduplicata contro il DB la genera
    lo script PHP di import in produzione, che ha visibilita' su tutto il
    catalogo gia' scritto."""
    if e_vuoto(testo):
        return ""
    testo = unidecode(str(testo)) if unidecode else str(testo)
    testo = testo.lower()
    testo = re.sub(r'[^a-z0-9]+', '-', testo)
    testo = re.sub(r'-+', '-', testo).strip('-')
    return testo[:128]


# ------------------------- CHIAMATA LIBRETRANSLATE + CACHE PERSISTENTE -------------------------

def _chiamata_libretranslate(testo, lingua_target, tentativi=3):
    # format "text": ogni frammento inviato e' ormai garantito privo di tag
    # e di codici (separati a monte), quindi non serve piu' la modalita'
    # HTML del traduttore (che si e' rivelata soggetta a bug di
    # troncamento/corruzione con certi input).
    payload = {"q": testo, "source": SOURCE_LANG, "target": lingua_target, "format": "text"}
    ultimo_errore = None
    for tentativo in range(1, tentativi + 1):
        try:
            with _semaforo_richieste:
                resp = requests.post(LIBRETRANSLATE_URL, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()["translatedText"]
        except Exception as e:
            ultimo_errore = e
            time.sleep(1.5 * tentativo)
    log(f"  [FALLITO] '{testo[:50]}...' -> {lingua_target}: {ultimo_errore} (riproverò al prossimo giro)")
    return FALLIMENTO


def carica_cache_persistente(conn):
    with _cache_lock:
        cur = conn.execute("SELECT testo_originale, lingua, traduzione FROM cache_traduzioni")
        for testo, lingua, trad in cur.fetchall():
            _cache_traduzioni[(testo, lingua)] = trad
    log(f"Cache persistente caricata: {len(_cache_traduzioni)} traduzioni già note (nessuna richiesta ripetuta).")


def _salva_in_cache_persistente(conn, testo_originale, lingua, traduzione):
    with _cache_db_lock:
        conn.execute(
            "INSERT INTO cache_traduzioni (testo_originale, lingua, traduzione) VALUES (?,?,?) "
            "ON CONFLICT(testo_originale, lingua) DO UPDATE SET traduzione=excluded.traduzione",
            (testo_originale, lingua, traduzione)
        )
        conn.commit()


def _traduci_e_valida(conn, testo_da_inviare, lingua_target):
    """Cache-aside sostenuta da SQLite. Se la risposta appena ricevuta
    sembra troncata/non tradotta, NON viene messa in cache (altrimenti
    resterebbe sbagliata per sempre) e verrà ritentata al giro successivo."""
    chiave = (testo_da_inviare, lingua_target)
    with _cache_lock:
        trovato = _cache_traduzioni.get(chiave)
    if trovato is not None:
        return trovato

    tradotto = _chiamata_libretranslate(testo_da_inviare, lingua_target)
    if tradotto is FALLIMENTO:
        return FALLIMENTO

    if _sembra_incompleta(testo_da_inviare, tradotto):
        log(f"  [SOSPETTO] risposta troncata/non tradotta, NON salvata in cache "
            f"(verrà ritentata): '{testo_da_inviare[:60]}...' -> '{tradotto[:60]}...'")
        return FALLIMENTO

    with _cache_lock:
        _cache_traduzioni[chiave] = tradotto
    _salva_in_cache_persistente(conn, testo_da_inviare, lingua_target, tradotto)
    return tradotto


def _traduci_frammento(conn, frammento, lingua_target, gestisci_maiuscolo=True):
    """Traduce UN pezzo di puro testo (nessun tag, nessun codice dentro —
    quelli sono già stati tolti prima di arrivare qui). Se il frammento è
    interamente in maiuscolo, lo manda al traduttore in forma normale
    (il traduttore spesso ignora il testo tutto maiuscolo e lo restituisce
    invariato) e rimette il maiuscolo dopo."""
    pulito = frammento.strip()
    if pulito == "" or not any(c.isalpha() for c in pulito):
        return frammento

    era_maiuscolo = gestisci_maiuscolo and e_tutto_maiuscolo(pulito)
    da_inviare = pulito.capitalize() if era_maiuscolo else pulito

    tradotto = _traduci_e_valida(conn, da_inviare, lingua_target)
    if tradotto is FALLIMENTO:
        return FALLIMENTO

    if era_maiuscolo:
        tradotto = tradotto.upper()

    spazi_prima = frammento[:len(frammento) - len(frammento.lstrip())]
    spazi_dopo = frammento[len(frammento.rstrip()):]
    return spazi_prima + tradotto + spazi_dopo


def traduci_con_protezione(conn, testo, lingua_target, e_html=False):
    """Traduce un testo tenendo SEMPRE fuori dalla richiesta i tag HTML
    (letterali, mai analizzati) e i codici/numeri (letterali, mai
    tradotti) — vengono ricomposti dopo, non recuperati da un segnaposto.
    Il maiuscolo/minuscolo viene gestito per singolo frammento di testo
    (dopo aver già isolato codici e tag), non sull'intera stringa —
    altrimenti un codice con lettere minuscole (es. '1 x') fa fallire il
    riconoscimento 'tutto maiuscolo' su tutta la frase."""
    if e_vuoto(testo):
        return ""
    testo = str(testo).strip()

    pezzi_finali = []
    for tipo_tag, val_tag in _dividi_per_tag(testo):
        if tipo_tag == "tag":
            pezzi_finali.append(val_tag)  # tag HTML: mai toccato
            continue
        for tipo_cod, val_cod in _dividi_codici(val_tag):
            if tipo_cod == "codice":
                pezzi_finali.append(val_cod)  # codice/numero: mai tradotto
                continue
            tradotto = _traduci_frammento(conn, val_cod, lingua_target, gestisci_maiuscolo=not e_html)
            if tradotto is FALLIMENTO:
                return FALLIMENTO
            pezzi_finali.append(tradotto)

    return "".join(pezzi_finali)


def traduci_tag(conn, campo_tag, lingua_target):
    if e_vuoto(campo_tag):
        return ""
    tag_list = [t.strip() for t in re.split(r'\s*,\s*', str(campo_tag)) if t.strip() != ""]
    tag_tradotti = []
    for t in tag_list:
        r = traduci_con_protezione(conn, t, lingua_target, e_html=False)
        if r is FALLIMENTO:
            return FALLIMENTO
        tag_tradotti.append(r)
    return SEPARATORE_TAG_OUTPUT.join(tag_tradotti)


# ------------------------- DISPATCH PER COLONNA -------------------------

def valore_sorgente_pulito(record_it, colonna):
    valore = record_it.get(colonna, "")
    if e_vuoto(valore):
        return ""
    return str(valore).strip()


def traduci_campo(conn, colonna, valore_pulito, lingua_target):
    if e_vuoto(valore_pulito):
        return ""
    if colonna == COLONNA_TAG:
        return traduci_tag(conn, valore_pulito, lingua_target)
    if colonna in ("riepilogo", "descrizione"):
        return traduci_con_protezione(conn, valore_pulito, lingua_target, e_html=True)
    if colonna == "nome":
        risultato = traduci_con_protezione(conn, valore_pulito, lingua_target, e_html=False)
        if risultato is not FALLIMENTO and len(risultato) > LUNGHEZZA_MAX_NOME:
            log(f"  [ATTENZIONE] nome tradotto supera {LUNGHEZZA_MAX_NOME} caratteri "
                f"({len(risultato)}): '{risultato[:60]}...'")
        return risultato
    # metatitolo, metadescrizione
    return traduci_con_protezione(conn, valore_pulito, lingua_target, e_html=False)


# ------------------------- SCANSIONE EXCEL -------------------------

def scansiona_foglio(percorso, nome_foglio, callback_progresso=None):
    try:
        wb = load_workbook(percorso, read_only=True, data_only=True)
    except FileNotFoundError:
        raise FileNotFoundError(f"File non trovato: {percorso}")

    if nome_foglio not in wb.sheetnames:
        wb.close()
        return []

    ws = wb[nome_foglio]
    righe_iter = ws.iter_rows(values_only=True)
    try:
        intestazione_raw = next(righe_iter)
    except StopIteration:
        wb.close()
        return []

    intestazione = [str(c).strip() if c is not None else "" for c in intestazione_raw]
    indice_colonne = {col: intestazione.index(col) for col in COLONNE_ATTESE if col in intestazione}

    if COLONNA_SKU not in indice_colonne:
        wb.close()
        raise ValueError(f"Colonna '{COLONNA_SKU}' non trovata nel foglio '{nome_foglio}'.")

    righe = []
    for riga in righe_iter:
        idx_sku = indice_colonne[COLONNA_SKU]
        valore_sku = riga[idx_sku] if idx_sku < len(riga) else None
        if valore_sku is None or str(valore_sku).strip() == "":
            break
        record = {COLONNA_SKU: str(valore_sku).strip()}
        for col in COLONNE_DA_TRADURRE:
            idx = indice_colonne.get(col)
            valore = riga[idx] if (idx is not None and idx < len(riga)) else None
            record[col] = "" if valore is None else str(valore)
        righe.append(record)

        if callback_progresso and len(righe) % 5000 == 0:
            callback_progresso(len(righe))

    wb.close()
    return righe


# ------------------------- DATABASE -------------------------

def apri_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def inizializza_db(conn):
    colonne_sql = ", ".join(f'"{c}" TEXT' for c in COLONNE_DA_TRADURRE)
    conn.execute(f'CREATE TABLE IF NOT EXISTS sorgente_it (sku TEXT PRIMARY KEY, {colonne_sql})')
    for lingua in TUTTE_LE_LINGUE:
        conn.execute(f'CREATE TABLE IF NOT EXISTS trad_{lingua} (sku TEXT PRIMARY KEY, {colonne_sql})')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS cache_traduzioni (
            testo_originale TEXT NOT NULL,
            lingua TEXT NOT NULL,
            traduzione TEXT NOT NULL,
            PRIMARY KEY (testo_originale, lingua)
        )
    ''')
    conn.commit()


def upsert_righe(conn, tabella, righe):
    if not righe:
        return
    colonne = [COLONNA_SKU] + COLONNE_DA_TRADURRE
    placeholders = ", ".join("?" for _ in colonne)
    colonne_sql = ", ".join(f'"{c}"' for c in colonne)
    aggiornamenti = ", ".join(f'"{c}"=excluded."{c}"' for c in COLONNE_DA_TRADURRE)
    sql = f'INSERT INTO {tabella} ({colonne_sql}) VALUES ({placeholders}) ON CONFLICT(sku) DO UPDATE SET {aggiornamenti}'
    valori = [tuple(r.get(c, "") for c in colonne) for r in righe]
    with _db_lock:
        conn.executemany(sql, valori)
        conn.commit()


def leggi_tabella_come_dict(conn, tabella):
    with _db_lock:
        cur = conn.execute(f"SELECT * FROM {tabella}")
        cols = [d[0] for d in cur.description]
        dati = cur.fetchall()
    return {dict(zip(cols, r))[COLONNA_SKU]: dict(zip(cols, r)) for r in dati}


# ------------------------- LEGENDA RICORRENZE (solo prima esecuzione) -------------------------

def analizza_e_salva_legenda(conn):
    if os.path.exists(LEGENDA_PATH):
        log(f"Legenda ricorrenze già presente ({LEGENDA_PATH}), salto l'analisi.")
        return

    log("Prima esecuzione: analizzo ricorrenze/pattern nel foglio 'it' (solo una volta)...")
    dati = leggi_tabella_come_dict(conn, "sorgente_it")
    legenda = {}

    for colonna in COLONNE_LOOP:
        conteggio = {}
        for sku, record in dati.items():
            valore = valore_sorgente_pulito(record, colonna)
            if e_vuoto(valore):
                continue
            info = conteggio.setdefault(valore, {"occorrenze": 0, "esempio_sku": sku})
            info["occorrenze"] += 1

        ripetuti = {v: info for v, info in conteggio.items() if info["occorrenze"] > 1}
        risparmio_chiamate = sum(i["occorrenze"] for i in ripetuti.values()) - len(ripetuti)

        legenda[colonna] = {
            "valori_distinti_totali": len(conteggio),
            "valori_ripetuti": len(ripetuti),
            "risparmio_chiamate_stimato": risparmio_chiamate,
            "dettaglio_ripetuti_top500": [
                {"testo": v[:300], "occorrenze": info["occorrenze"], "esempio_sku": info["esempio_sku"]}
                for v, info in sorted(ripetuti.items(), key=lambda kv: -kv[1]["occorrenze"])[:500]
            ],
        }
        log(f"  colonna '{colonna}': {len(conteggio)} valori distinti, {len(ripetuti)} ripetuti "
            f"(risparmio stimato: {risparmio_chiamate} chiamate grazie alla cache)")

    with open(LEGENDA_PATH, "w", encoding="utf-8") as f:
        json.dump(legenda, f, ensure_ascii=False, indent=2)
    log(f"Legenda salvata in {LEGENDA_PATH}.")


# ------------------------- WORKER PER LINGUA (sequenziale) -------------------------

def worker_lingua(lingua, righe_it):
    try:
        _worker_lingua_impl(lingua, righe_it)
    except Exception:
        log(f"[{lingua}] ERRORE FATALE — il thread si è interrotto:\n{traceback.format_exc()}")
        with _stato_lock:
            if lingua in stato_lingue:
                stato_lingue[lingua]["stato"] = "ERRORE"


def _worker_lingua_impl(lingua, righe_it):
    conn = apri_db()
    esistenti = leggi_tabella_come_dict(conn, f"trad_{lingua}")
    totale = len(righe_it)

    with _stato_lock:
        stato_lingue[lingua] = {"processate": 0, "totale": totale, "tradotte": 0,
                                 "saltate": 0, "fallite": 0, "stato": "in corso", "inizio": time.time()}

    log(f"[{lingua}] avviato — {totale} righe da esaminare.")
    batch_scrittura = []

    for record_it in righe_it:
        if stop_event.is_set():
            break

        sku = record_it[COLONNA_SKU]
        riga_target = dict(esistenti.get(sku, {COLONNA_SKU: sku, **{c: "" for c in COLONNE_DA_TRADURRE}}))
        modificata = False
        fallimento_riga = False

        for colonna in COLONNE_LOOP:
            sorgente_pulita = valore_sorgente_pulito(record_it, colonna)
            valore_attuale = riga_target.get(colonna, "")

            if e_vuoto(sorgente_pulita):
                if valore_attuale != "":
                    riga_target[colonna] = ""
                    modificata = True
                continue

            gia_tradotta = not e_vuoto(valore_attuale)
            sospetta = gia_tradotta and _risultato_sospetto(sorgente_pulita, valore_attuale)

            if gia_tradotta and not sospetta:
                continue  # guardia: già tradotto e sembra valido -> ok così

            if sospetta:
                log(f"  [{lingua}] sku={sku} colonna='{colonna}': valore già presente ma sospetto "
                    f"(identico o troncato rispetto all'italiano), ritento la traduzione.")

            risultato = traduci_campo(conn, colonna, sorgente_pulita, lingua)
            if risultato is FALLIMENTO:
                fallimento_riga = True
                continue

            if _risultato_sospetto(sorgente_pulita, risultato):
                log(f"  [{lingua}] sku={sku} colonna='{colonna}': risultato appena arrivato sembra "
                    f"ancora non tradotto/troncato — SCARTATO, non scritto (verrà ritentato al prossimo giro): "
                    f"'{risultato[:60]}...'")
                fallimento_riga = True
                continue

            if risultato != valore_attuale:
                riga_target[colonna] = risultato
                modificata = True

        # url_rewritten: deterministico, ricalcolato sempre dal nome corrente della riga
        nome_corrente = riga_target.get("nome", "")
        slug_atteso = genera_slug(nome_corrente) if nome_corrente else ""
        if riga_target.get(COLONNA_URL, "") != slug_atteso:
            riga_target[COLONNA_URL] = slug_atteso
            modificata = True

        if modificata:
            batch_scrittura.append(riga_target)
            esistenti[sku] = riga_target
            with _stato_lock:
                stato_lingue[lingua]["tradotte"] += 1
        else:
            with _stato_lock:
                stato_lingue[lingua]["saltate"] += 1

        if fallimento_riga:
            with _stato_lock:
                stato_lingue[lingua]["fallite"] += 1

        with _stato_lock:
            stato_lingue[lingua]["processate"] += 1

        if len(batch_scrittura) >= BATCH_SIZE:
            upsert_righe(conn, f"trad_{lingua}", batch_scrittura)
            batch_scrittura = []

    if batch_scrittura:
        upsert_righe(conn, f"trad_{lingua}", batch_scrittura)

    with _stato_lock:
        stato_lingue[lingua]["stato"] = "interrotto" if stop_event.is_set() else "completato"

    log(f"[{lingua}] {'interrotto' if stop_event.is_set() else 'completato'} "
        f"({stato_lingue[lingua]['processate']}/{totale}).")
    conn.close()


# ------------------------- EXPORT (thread indipendente, non blocca mai la traduzione) -------------------------

def esporta_tutto_su_excel():
    conn = apri_db()
    file_temp = FILE_PATH + f".tmp_export_{os.getpid()}"

    try:
        wb = Workbook(write_only=True)

        ws_it = wb.create_sheet(SHEET_ORIGINE)
        ws_it.append(COLONNE_ATTESE)
        for record in leggi_tabella_come_dict(conn, "sorgente_it").values():
            ws_it.append([record.get(c, "") for c in COLONNE_ATTESE])

        for lingua in TUTTE_LE_LINGUE:
            ws = wb.create_sheet(lingua)
            ws.append(COLONNE_ATTESE)
            for record in leggi_tabella_come_dict(conn, f"trad_{lingua}").values():
                ws.append([record.get(c, "") for c in COLONNE_ATTESE])

        wb.save(file_temp)
        os.replace(file_temp, FILE_PATH)
    except Exception:
        if os.path.exists(file_temp):
            os.remove(file_temp)
        raise
    finally:
        conn.close()


def thread_esportazione():
    while not stop_event.wait(timeout=EXPORT_INTERVALLO_SECONDI):
        try:
            log("Export periodico su Excel (rigenerazione completa da database)...")
            t0 = time.time()
            esporta_tutto_su_excel()
            ultimo_export["quando"] = time.time()
            ultimo_export["stato"] = "ok"
            log(f"Export periodico completato in {time.time() - t0:.0f}s.")
        except Exception as e:
            ultimo_export["stato"] = f"errore: {e}"
            log(f"  [ATTENZIONE] export periodico fallito: {e}")

    try:
        log("Export finale su Excel...")
        t0 = time.time()
        esporta_tutto_su_excel()
        ultimo_export["quando"] = time.time()
        ultimo_export["stato"] = "ok (finale)"
        log(f"Export finale completato in {time.time() - t0:.0f}s.")
    except Exception as e:
        ultimo_export["stato"] = f"errore export finale: {e}"
        log(f"  [ATTENZIONE] export finale fallito: {e}")


# ------------------------- SCANSIONE INIZIALE -------------------------

def fase_scansione(conn):
    log("Scansione foglio sorgente 'it'...")
    righe_it = scansiona_foglio(
        FILE_PATH, SHEET_ORIGINE,
        callback_progresso=lambda n: log(f"  ... {n} righe lette finora")
    )
    log(f"  -> {len(righe_it)} righe trovate.")
    upsert_righe(conn, "sorgente_it", righe_it)

    for lingua in TUTTE_LE_LINGUE:
        righe_lingua = scansiona_foglio(FILE_PATH, lingua)
        upsert_righe(conn, f"trad_{lingua}", righe_lingua)
        log(f"Scansione '{lingua}': {len(righe_lingua)} righe già presenti importate.")

    return righe_it


def avvia_elaborazione():
    try:
        _avvia_elaborazione_impl()
    except Exception:
        log(f"ERRORE FATALE nell'avvio dell'elaborazione:\n{traceback.format_exc()}")


def _avvia_elaborazione_impl():
    log(f"Questa istanza tradurrà: {', '.join(LINGUE_DESTINAZIONE)} (PID {os.getpid()})")
    if LIMITE_RIGHE:
        log(f"MODALITA' TEST: elaboro solo le prime {LIMITE_RIGHE} righe.")

    conn = apri_db()
    inizializza_db(conn)
    righe_it = fase_scansione(conn)

    analizza_e_salva_legenda(conn)      # solo se non già fatta in un run precedente
    carica_cache_persistente(conn)       # precarica tutte le traduzioni già note

    conn.close()

    if not righe_it:
        log("Nessuna riga trovata nel foglio sorgente. Controlla il file.")
        return

    righe_da_elaborare = righe_it[:LIMITE_RIGHE] if LIMITE_RIGHE else righe_it

    thread_export = threading.Thread(target=thread_esportazione, daemon=True)
    thread_export.start()

    thread_lingue = []
    for lingua in LINGUE_DESTINAZIONE:
        t = threading.Thread(target=worker_lingua, args=(lingua, righe_da_elaborare), daemon=True)
        t.start()
        thread_lingue.append(t)

    for t in thread_lingue:
        t.join()

    log("Tutte le lingue completate/interrotte. Attendo l'export finale...")
    stop_event.set()
    thread_export.join()
    log("Elaborazione terminata.")


# ------------------------- GUI -------------------------

class App:
    def __init__(self, root):
        self.root = root
        root.title("Traduzione catalogo — avanzamento")
        root.geometry("1000x580")
        root.minsize(920, 520)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        frame_top = ttk.Frame(root, padding=10)
        frame_top.pack(fill="x")

        self.barre = {}
        self.label_stato = {}
        font_mono = ("Consolas", 10)

        for lingua in LINGUE_DESTINAZIONE:
            riga = ttk.Frame(frame_top)
            riga.pack(fill="x", pady=4)
            ttk.Label(riga, text=lingua.upper(), width=4, font=("Segoe UI", 10, "bold")).pack(side="left")
            barra = ttk.Progressbar(riga, length=280, mode="determinate", maximum=100)
            barra.pack(side="left", padx=8)
            lbl = ttk.Label(riga, text="in attesa...", width=72, font=font_mono, anchor="w")
            lbl.pack(side="left", fill="x", expand=True)
            self.barre[lingua] = barra
            self.label_stato[lingua] = lbl

        self.label_export = ttk.Label(root, text="Export: non ancora eseguito", font=("Segoe UI", 9), padding=(10, 0))
        self.label_export.pack(fill="x")

        self.log_box = scrolledtext.ScrolledText(root, height=16, state="disabled", font=("Consolas", 9), wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=10, pady=(5, 5))

        frame_btn = ttk.Frame(root, padding=10)
        frame_btn.pack(fill="x")
        self.btn_stop = ttk.Button(frame_btn, text="Ferma (interruzione pulita)", command=self.ferma)
        self.btn_stop.pack(side="left")

        self.root.after(300, self.aggiorna)

    def ferma(self):
        stop_event.set()
        self.btn_stop.config(text="Interruzione in corso (in attesa dell'export finale)...", state="disabled")

    def on_close(self):
        stop_event.set()
        self.root.after(500, self.root.destroy)

    def aggiorna(self):
        while True:
            try:
                msg = log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_box.config(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.config(state="disabled")

        with _stato_lock:
            snapshot = {k: dict(v) for k, v in stato_lingue.items()}

        for lingua, dati in snapshot.items():
            totale = max(dati["totale"], 1)
            percentuale = dati["processate"] / totale * 100
            self.barre[lingua]["value"] = percentuale

            trascorso = time.time() - dati["inizio"]
            velocita = dati["processate"] / trascorso if trascorso > 0 else 0

            if dati["stato"] == "in corso" and velocita > 0:
                eta_min = (totale - dati["processate"]) / velocita / 60
                eta_txt = f"ETA {eta_min:6.0f} min"
            elif dati["stato"] != "in corso":
                eta_txt = f"tot {trascorso/60:5.1f} min"
            else:
                eta_txt = "ETA   --- "

            testo = (f"{dati['processate']:>6}/{totale:<6} ({percentuale:5.1f}%) "
                     f"trad:{dati['tradotte']:<5} salt:{dati['saltate']:<5} "
                     f"fall:{dati['fallite']:<4} {eta_txt} [{dati['stato']}]")
            self.label_stato[lingua].config(text=testo)

        if ultimo_export["quando"]:
            secondi_fa = time.time() - ultimo_export["quando"]
            self.label_export.config(text=f"Ultimo export Excel: {secondi_fa:.0f}s fa — stato: {ultimo_export['stato']}")
        else:
            self.label_export.config(text=f"Export: {ultimo_export['stato']}")

        self.root.after(300, self.aggiorna)


def main():
    root = tk.Tk()
    App(root)

    thread_lavoro = threading.Thread(target=avvia_elaborazione, daemon=True)
    thread_lavoro.start()

    root.mainloop()


if __name__ == "__main__":
    main()
