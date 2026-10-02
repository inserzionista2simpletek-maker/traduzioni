# SPEC — traduci-catalogo

## Obiettivo
Pacchetto Python pulito che, dato un Excel di catalogo con foglio `it`, produce le traduzioni
per en/fr/es/de/pt/pl/ro via LibreTranslate, in modo **ripristinabile, idempotente, verificabile**,
senza mai toccare il file di input, con report finale. Sostituisce `legacy/traduci_catalogo_gui.py`
mantenendone i comportamenti buoni (vedi fondo di `ANALISI-BUG.md`) e correggendone i difetti.

## Dati
Foglio `it` + un foglio per lingua. Colonne: `sku, nome, riepilogo, descrizione, metatitolo,
metadescrizione, tag, url_rewritten`.
- `sku`: chiave, mai tradotto.
- `nome`, `metatitolo`, `metadescrizione`: testo semplice.
- `riepilogo`: HTML con template ricorrente `<p><strong>Etichetta: </strong>Valore</p>` (più righe).
- `descrizione`: HTML reale (tag + attributi da preservare).
- `tag`: sorgente separato da virgola; output separato da `$` (da verificare, A12).
- `url_rewritten`: NON tradotto, anteprima slug dal nome tradotto (simile a `Tools::str2url()` di PrestaShop).

## Requisiti funzionali
1. **Input/output separati**: legge `--input catalogo.xlsx`, scrive `--output catalogo_tradotto.xlsx`. Mai sovrascrive l'input.
2. **DB SQLite = fonte di verità** (stato, cache, hash sorgente per cella, stato per cella). Excel di input solo importato (A2).
3. **Idempotente e riprendibile**: rilanciare non ritraduce ciò che è valido; ritraduce solo se il sorgente è cambiato (hash, A6) o la cella è in errore.
4. **Traduttore astratto** `Translator.translate(list[str], target) -> list[str]` con `LibreTranslateClient` (batch, retry
   selettivo, backoff, `api_key` opzionale, timeout) e `FakeTranslator` per i test.
5. **Protezione di HTML, entità, codici/numeri/unità** con segnaposto **validati** (tornano tutti, una volta sola) e fallback
   (A8, A9). Scelta del formato segnaposto motivata da test.
6. **Stati per cella**: `ok`, `identico_ammesso`, `sospetto`, `errore`, `vuoto`. Euristiche con soglie configurabili (A7).
7. **`riepilogo`**: parser del template con cache di etichette/valori + fallback HTML protetto (A11).
8. **Tag**: lista da virgola, ciascuno tradotto/cached, separatore output configurabile (A12).
9. **Slug**: `unidecode` obbligatorio; limiti PrestaShop con report (A13, A14).
10. **Report finale** CSV/JSON per sku/colonna/lingua: tradotta, da cache, fallita, sospetta, oltre-limite (C6).
11. **CLI** (`python -m traduci_catalogo ...`): `--lingue en fr`, `--limit N`, `--dry-run`, `--rebuild-legenda`, `--workers`, `--url`, `--db`, config da file/ENV.
    **GUI tkinter opzionale** (sottile, sopra lo stesso motore) con avanzamento per lingua e pulsante stop pulito.
12. **Logging su file** con rotazione (C3).
13. Un solo processo, thread per lingua + limite globale di richieste concorrenti (B4).

## Requisiti non funzionali
- Python >= 3.10, Windows-friendly. Dipendenze: `requests`, `openpyxl`, `unidecode`; dev: `pytest`.
- Testabile offline al 100%. Copertura test sensata su: protezione/ripristino segnaposto, parser riepilogo,
  guardie sospetto, slug, lettura Excel (righe vuote, sku numerici), ripresa dopo interruzione, hash sorgente, client HTTP (mock).
- Stima prestazioni: a catalogo grande (~decine di migliaia di righe × 7 lingue) il numero di richieste HTTP deve calare
  di un ordine di grandezza rispetto al legacy (batch).

## Struttura proposta
```
src/traduci_catalogo/
  __init__.py  __main__.py  cli.py  config.py
  excel_io.py      # lettura/scrittura xlsx
  storage.py       # sqlite: sorgente, traduzioni, cache, hash
  protect.py       # tag/entità/codici -> segnaposto validati
  translator.py    # interfaccia + LibreTranslateClient + FakeTranslator
  engine.py        # orchestrazione per lingua, thread, stati
  fields.py        # regole per colonna (nome, riepilogo, tag, ...)
  slug.py  report.py  gui.py
tests/  tools/make_sample_xlsx.py
```

## Piano a fasi (aggiornare in docs/STATO.md)
0. Scaffolding: `pyproject.toml`, `requirements*.txt`, struttura, pytest che gira, `make_sample_xlsx.py`.
1. `protect.py` + test (cuore qualitativo: A8, A9, A10) — con esperimenti documentati sui formati di segnaposto.
2. `translator.py` (interfaccia, Fake, client con batch/retry) + test con mock HTTP.
3. `storage.py` + `excel_io.py` (A1-A5, A6) + test.
4. `fields.py` + `engine.py` (stati, A7, A11, A12) + test di ripresa/idempotenza.
5. `slug.py`, limiti PS, `report.py` (A13, A14, C6).
6. CLI, logging, config (C1, C3, C5, B2-B8).
7. GUI sottile (opzionale) + README d'uso + aggiornamento `docs/TRASFERIMENTO.md`.
Ogni fase: test verdi, commit, `docs/STATO.md` aggiornato.

## Collaudo reale (lo fa l'utente in locale, NON nel cloud)
Dopo il lavoro cloud, sulla macchina locale con LibreTranslate vero e un estratto reale del catalogo:
1. `--dry-run`, poi `--limit 50` su una lingua; ispezione a campione (codici intatti, HTML integro, nomi sensati).
2. Confronto con l'output del legacy sulle stesse righe.
3. Solo dopo: run completo. L'import in produzione resta un passo separato e con conferma.

## Domande aperte (default raccomandato tra parentesi)
1. **Forma del "modulo"**: tool Python autonomo CLI+GUI (default) oppure modulo PrestaShop PHP? LibreTranslate gira in locale su GPU,
   quindi un modulo PS in produzione non potrebbe raggiungerlo: il default è il tool Python che produce l'Excel per l'import PHP esistente.
   Se serve davvero un modulo PS, sarà una fase successiva che consuma l'output di questo tool.
2. Separatore tag `$`: da dove viene, è richiesto dall'import? (default: configurabile, `$`)
3. Limiti lunghezza: nome / metatitolo / metadescrizione / url. (default: nome 128 hard, 80 warning; metatitolo 70 warning; metadescrizione 160 warning; url 128)
4. Colonne extra nel foglio `it`: preservarle in output? (default: sì, copiate invariate)
5. Per frasi tutte maiuscole: inviare maiuscolo così com'è, o normalizzare? (default: decidere con test sul traduttore reale in fase di collaudo; configurabile)
