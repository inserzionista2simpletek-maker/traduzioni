# Analisi del codice legacy (`legacy/traduci_catalogo_gui.py`)

Riferimenti = numeri di riga del file legacy. Spuntare `[x]` quando corretto + test di regressione.
Priorità: **A** = perdita/corruzione dati o risultato sbagliato, **B** = qualità/performance, **C** = manutenzione.

## A — Correttezza e integrità dati

- [ ] **A1. Il file Excel di input viene sovrascritto** (694, 711). `FILE_PATH` è sia sorgente sia destinazione:
      l'export fa `os.replace` sul file originale. Se l'utente modifica l'Excel nel frattempo, perde le modifiche;
      se è aperto in Excel su Windows l'`os.replace` fallisce (PermissionError). Servono input e output separati.
- [ ] **A2. All'avvio l'Excel sovrascrive il DB** (754, 757-758, 528). `upsert_righe(... ON CONFLICT DO UPDATE)`
      riversa nel DB le righe lette dall'Excel. Se il DB è più avanti dell'Excel (crash tra due export, export
      ogni 5 min) si perde lavoro; con più istanze in parallelo la seconda avviata sovrascrive righe che la prima
      sta traducendo. Il DB deve essere la fonte di verità; l'Excel di input si importa solo per il sorgente `it`
      (e le traduzioni pregresse solo se la cella nel DB è vuota).
- [ ] **A3. Lettura Excel si ferma alla prima riga con sku vuoto** (479-480, `break`). Una riga vuota in mezzo
      tronca silenziosamente il catalogo. Va saltata (con warning) e non interrompere; contare e riportare le righe scartate.
- [ ] **A4. Sku/celle numeriche** (485, `str(valore)`). Con `data_only=True` uno sku numerico diventa `12345` o
      `12345.0`, e si perdono gli zeri iniziali. Normalizzare (int-like float → int, preservare testo) e loggare.
- [ ] **A5. Colonne extra perse**: l'export scrive solo `COLONNE_ATTESE` (704-708); eventuali altre colonne del foglio `it` sparirebbero.
      Decidere (SPEC) se preservarle.
- [ ] **A6. Traduzioni obsolete mai aggiornate** (626-630): se il testo italiano cambia dopo la traduzione, la cella
      "già tradotta e non sospetta" viene tenuta. Salvare un hash del sorgente per cella e ritradurre se cambia.
- [ ] **A7. Falsi positivi della guardia "sospetto"** (192-221, 627, 641): un risultato identico all'italiano è scartato
      anche quando è legittimo (nomi/marchi/modelli, tag come "USB", testi di soli codici). Il valore non viene mai scritto,
      la riga resta vuota e conta come `fallita` a ogni run. Idem `_sembra_incompleta` (211): `len(r) < 50% len(s)` scatta
      su lingue più concise (es. tedesco/inglese) o testi con molte ripetizioni. Servono: whitelist/regola "identico ammesso
      se il sorgente non contiene parole traducibili", soglie per lingua, e uno stato esplicito (`ok / identico_ammesso / sospetto / errore`).
- [ ] **A8. Frammentazione del testo = traduzioni scadenti** (233-239, 258-271, 380-406). Ogni codice/numero spezza la frase:
      "Batteria da 3000mAh per iPhone 12" → tre richieste ("Batteria da", "per iPhone") senza contesto, ordine delle parole
      per lingua non rispettato, genere/articoli sbagliati. Preferire il pattern segnaposto **ma validato**
      (verifica che ogni segnaposto torni nel risultato, una sola volta; altrimenti fallback frammentato) oppure frasi intere.
      Il commento a 227-229 dice che i segnaposto erano "inaffidabili": riprodurre con test (tag `<x id="n"/>`, `[[n]]`, ecc.) e scegliere con evidenza.
- [ ] **A9. Entità HTML** (`&nbsp;`, `&amp;`, `&egrave;` …): non hanno cifre, quindi finiscono come testo al traduttore
      (format=text) e vengono corrotte/spezzate. Proteggerle o decodificarle/ricodificarle.
- [ ] **A10. `capitalize()` sui testi TUTTI MAIUSCOLI** (366): abbassa tutto il resto ("APPLE IPHONE" → "Apple iphone")
      e il `.upper()` finale non recupera nulla di sensato per i nomi propri; il testo inviato è degradato. Valutare alternative
      (inviare così com'è; ripristinare case dopo; per i soli nomi).
- [ ] **A11. Docstring ≠ codice per `riepilogo`** (27-32 vs 436-437): la docstring descrive un parser del template
      `<p><strong>Etichetta: </strong>Valore</p>` con cache etichette/valori e fallback. Il codice non lo implementa: tratta `riepilogo` come HTML qualsiasi.
      Decidere se implementarlo (consigliato: etichette ripetute = grande risparmio + coerenza) e documentare.
- [ ] **A12. Separatore tag `$`** (144, 419): input separato da virgola, output da `$`. Verificare con l'utente a cosa serve
      (formato dell'import PHP?) e renderlo configurabile + documentato. Tag con virgola interna non gestiti.
- [ ] **A13. Slug**: `unidecode` è opzionale (89-92); senza, le lettere accentate vengono eliminate dalla regex (`[^a-z0-9]+` → `-`) e
      lo slug è sbagliato ("caffè" → "caff"). Rendere obbligatoria. Slug solo come anteprima: non gestisce duplicati (lo dice la
      docstring: li gestisce l'import PHP) — documentare il contratto.
- [ ] **A14. Limiti PrestaShop non verificati** (152, 440-443): solo `nome` ha un warning (>80). Mancano controlli su
      `metatitolo`, `metadescrizione`, `url_rewritten`(128), `nome`(128 nel DB) con report a fine run. Verificare i valori
      reali con l'utente (SPEC, domande aperte).

## B — Robustezza, performance

- [ ] **B1. Una richiesta HTTP per frammento** (297, 302): LibreTranslate accetta `q` come lista → batch di decine di
      frammenti per richiesta. Enorme guadagno (oggi migliaia di richieste da 1 frase).
- [ ] **B2. Retry su qualsiasi errore** (299-307): anche su 4xx (lingua non caricata, payload errato) e ritenta 3 volte con sleep.
      Distinguere errori transitori (timeout, 5xx, 429 con backoff) da permanenti (400/403), log chiaro. Supporto `api_key` LibreTranslate.
- [ ] **B3. Commit SQLite a ogni traduzione** (320-327): lento. Batch di commit; cache in memoria + write-behind.
- [ ] **B4. Cache letta una volta sola all'avvio** (312-317): più istanze non vedono le traduzioni l'una dell'altra.
      Se si mantiene il multi-processo, leggere dal DB on-miss; meglio un solo processo con più thread per lingua.
- [ ] **B5. Export = rigenerazione completa ogni 5 min** (692-731, 535-540): carica intere tabelle in RAM, riscrive 8 fogli.
      Con decine di migliaia di righe è pesante e blocca l'Excel aperto (A1). Export a richiesta/fine run + checkpoint rado.
- [ ] **B6. Spegnimento** (854-856): `on_close` distrugge la finestra dopo 500 ms mentre l'export finale è in un thread daemon:
      può essere interrotto lasciando `*.tmp_export_*`. Attendere la fine o pulire i tmp all'avvio.
- [ ] **B7. Test-mode `--limit`** (789): limita righe ma l'export finale riscrive comunque tutto il file (A1).
- [ ] **B8. `traduzioni_progress.db` / `legenda_ricorrenze.json` in `Downloads`** (96-99): path fissi, legenda calcolata una sola volta
      (se il catalogo cambia resta vecchia). Rendere configurabile, rigenerabile (`--rebuild-legenda`).

## C — Manutenzione

- [ ] **C1. Parsing argv a livello di modulo** (105-135, 135): `sys.exit` in import, non testabile, non importabile.
- [ ] **C2. Un solo file da ~900 righe con stato globale** (semafori, cache, `stato_lingue`): separare engine / storage / excel / gui / cli.
- [ ] **C3. Nessun log su file**: i log vivono solo nella coda della GUI (176-178) e si perdono. Logging standard su file con rotazione.
- [ ] **C4. Nessun test, nessun `requirements.txt`**.
- [ ] **C5. Modalità headless** (solo GUI tkinter): servono CLI per esecuzione non presidiata; la GUI diventa uno strato sottile opzionale.
- [ ] **C6. Nessun report finale** per sku/colonna: quante tradotte, riusate da cache, fallite, sospette, troppo lunghe. Produrre un CSV/JSON di report.

## Note positive da conservare (comportamenti voluti)
- Ripresa dopo crash (stato su SQLite, commit a batch).
- Cache persistente cross-run per (testo, lingua).
- Non scrivere mai un risultato sospetto (ma vedi A7 per i falsi positivi).
- Un thread per lingua, limite globale di richieste concorrenti.
- `sku` mai tradotto; join tra fogli per `sku`.
- Codici/numeri/unità e tag HTML mai passati al traduttore (ma vedi A8/A9 sul *come*).
