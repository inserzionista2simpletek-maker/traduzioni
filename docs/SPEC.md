# SPEC — modulo PrestaShop `simpletektraduzioni`

> Revisione 2026-10-02: l'utente ha confermato che vuole un **modulo custom PrestaShop** (non un tool Python).
> `legacy/traduci_catalogo_gui.py` (Python) è il **riferimento di comportamento** da portare in PHP, correggendone i difetti.

## Obiettivo
Modulo PrestaShop 8.1.7 (PHP 8.1+ web, 8.3 CLI) che traduce i testi dei prodotti dall'italiano in
en, fr, es, de, pt, pl, ro tramite **LibreTranslate** (self-hosted dall'utente), in modo
**spento di default, ripristinabile, idempotente, verificabile**, con una fase di revisione prima di
scrivere nel catalogo. Convenzioni obbligatorie dei moduli SimpleTek: `docs/CONVENZIONI-MODULI-SIMPLETEK.md`.

## Principio di sicurezza centrale
Il modulo **non scrive mai direttamente nel catalogo mentre traduce**. Tre stadi:
1. **Traduzione → area di staging** (tabelle proprie `ps_stktrad_*`): testo sorgente, hash, traduzione, stato per cella.
2. **Revisione** nel BO (anteprima, filtri per stato, esclusioni, report limiti).
3. **Applicazione** al catalogo (`ps_product_lang`, tag): azione esplicita dell'utente, **una lingua per volta**,
   *marcia a secco ACCESA di default*, scrive SOLO su quell'`id_lang`, solo dove la cella di destinazione è vuota
   (o con flag esplicito "sovrascrivi"), con registro di cosa è stato cambiato (per poter tornare indietro).
In alternativa/in aggiunta: **export CSV/Excel** compatibile con l'import nativo di PrestaShop (una lingua per file).

## Dati
- Sorgente: testi italiani dei prodotti (`ps_product_lang` con `id_lang` = lingua italiana, risolta da ISO `it`, mai numero fisso).
  Chiave di prodotto = `reference` (sku) e `id_product`. In fase di sviluppo cloud la sorgente è dietro un'interfaccia `SourceRepository`
  (implementazione in-memory per i test + implementazione PS reale). Sorgente alternativa opzionale: file Excel/CSV con foglio `it` (stessi nomi colonna del legacy).
- Campi tradotti (nomi legacy → colonne PS): `nome`→`name`, `riepilogo`→`description_short`, `descrizione`→`description`,
  `metatitolo`→`meta_title`, `metadescrizione`→`meta_description`, `tag`→tag del prodotto, `url_rewritten`→`link_rewrite`.
- `sku`/`reference`: mai tradotto.
- `riepilogo`: HTML con template ricorrente `<p><strong>Etichetta: </strong>Valore</p>`.
- `descrizione`: HTML reale (tag e attributi da preservare).
- `link_rewrite`: NON tradotto; derivato dal nome tradotto con **`Tools::str2url()` reale** del core (in test: porta fedele in una classe `Slug`),
  con deduplica rispetto agli altri prodotti della stessa lingua (il legacy delegava questo all'import PHP: ora lo fa il modulo).
- Tag: sorgente separato da virgola. Nell'output CSV per l'import nativo il separatore va **verificato** sul codice reale dell'import (domanda aperta 2).

## Architettura (pattern SimpleTek: motore puro + guscio sottile)
```
simpletektraduzioni/
  simpletektraduzioni.php          # guscio: install/uninstall/hook/getContent; nessuna logica di traduzione
  classes/
    TradProtect.php                # tag/entità/codici -> segnaposto VALIDATI (puro)
    TradTranslator.php             # interfaccia translate(array $testi, string $iso): array
    TradLibreTranslateClient.php   # curl: batch, retry selettivo, backoff, api_key opzionale
    TradFakeTranslator.php         # per i test
    TradFields.php                 # regole per campo (nome, riepilogo, tag, meta...)
    TradEngine.php                 # orchestrazione per lingua, stati cella, euristiche (puro, senza PS)
    TradSlug.php  TradLimits.php   # slug e limiti lunghezza
    TradSourceRepository.php (+ In-memory, + PS)   TradStore.php (+ In-memory, + Db)
    TradWorker.php                 # esecuzione a lotti con budget di tempo, lock, ripresa
    TradApply.php                  # staging -> catalogo (secco/reale, una lingua, registro)
    TradReport.php  TradConfig.php
  upgrade/  views/  tests/  README.md  PIANO.md
cron/ (o controllers/) worker CLI    # PHP CLI 8.3, lock in sys_get_temp_dir(), MAI nella cartella del modulo
```
Il motore non include né usa classi PrestaShop: così gira nei test del cloud senza PS (PHPUnit).

## Requisiti funzionali (mappa sui difetti: `docs/ANALISI-BUG.md`)
1. Interruttore generale **SPENTO** all'installazione; "marcia a secco" ACCESA. Installare non cambia nulla di ciò che vedono i clienti.
2. Stato per cella in `ps_stktrad_*` con **hash del sorgente**: ritraduce solo se il sorgente cambia o la cella è in errore (A6).
3. Stati cella: `ok`, `identico_ammesso`, `sospetto`, `errore`, `vuoto`, `escluso`; soglie per lingua configurabili (A7).
4. `Translator` astratto, richieste **in batch** (lista di stringhe per chiamata), retry solo su errori transitori (timeout, 5xx, 429 con backoff),
   `api_key` opzionale, timeout configurabile, URL configurabile (B1, B2).
5. Protezione HTML/entità/codici/unità con **segnaposto validati** (tornano tutti e una volta sola, altrimenti fallback a frammenti) (A8, A9, A10).
   Scegliere il formato del segnaposto **con evidenza** (test, e poi collaudo reale: non si può sapere dal cloud come reagisce Argos/LibreTranslate).
6. `riepilogo`: parser del template con cache etichette/valori + fallback HTML protetto (A11).
7. Cache persistente (testo normalizzato, lingua) condivisa tra prodotti; scritture a lotti (B3).
8. Worker CLI a lotti con **budget di tempo**, lock con `flock` in `sys_get_temp_dir()`, uscita pulita, ripresa, e **salute** (timestamp ultimo giro) anche a modulo OFF (B4, B6).
   Un solo worker per volta (anti doppio-worker); mai bloccare il sito.
9. Pagina BO (`getContent`): interruttore, URL/chiave LibreTranslate, lingue attive, "Prova connessione", avanzamento per lingua, report
   (tradotte/da cache/errori/sospette/oltre-limite), elenco celle sospette con azioni (riprova, accetta, escludi), pulsante "Applica" (secco/reale) per una lingua, export CSV (C6).
10. Limiti PrestaShop con report: `name` 128, `meta_title` 128, `meta_description` 255, `link_rewrite` 128 (verificare sul DB reale, domanda 3) (A14).
11. Slug con `Tools::str2url()` e deduplica (A13).
12. Log: `PrestaShopLogger` per eventi gravi + log del worker su file in `var/logs/` (C3).
13. Upgrade: file in `upgrade/` ; installazione e disinstallazione che non lasciano orfani; **non** cancellare le traduzioni applicate al catalogo alla disinstallazione.

## Requisiti non funzionali
- PHP >= 8.1 (lint anche 8.3), PrestaShop 8.1.7, compatibilità dichiarata come gli altri moduli. Niente Composer in produzione: il modulo non deve richiedere `vendor/` a runtime (Composer solo per i test).
- Tutto il codice del motore testabile offline con PHPUnit. Copertura: protezione/ripristino, parser riepilogo, stati cella, hash/obsolescenza, batching,
  ripresa dopo interruzione, slug+deduplica, limiti, client HTTP contro un server mock locale (`php -S`) mai rete reale.
- Sicurezza: endpoint/cron non raggiungibili dal web (vedi CONVENZIONI: nginx scavalca .htaccess; file `.php` di worker solo CLI con guardia `PHP_SAPI`),
  token mai in query string, input validato, `pSQL`, nessun segreto nel repo.
- Prestazioni: richieste HTTP di un ordine di grandezza in meno del legacy (batch); nessuna operazione che carichi l'intero catalogo in memoria.

## Piano a fasi (aggiornare in `docs/STATO.md`)
0. Scaffolding: `composer.json` (solo dev: phpunit) alla radice, cartella `simpletektraduzioni/` con guscio minimo, `phpunit.xml`, test che girano senza PS; se PHP non è nell'ambiente cloud, installarlo e annotarlo.
1. `TradProtect` + test: esperimenti documentati su formati di segnaposto (A8, A9, A10).
2. `TradTranslator`, client LibreTranslate (batch/retry), fake; test con server mock locale.
3. Interfacce `TradStore`/`TradSourceRepository` + in-memory; stati cella, hash, cache (A6, A7, B3).
4. `TradFields` + `TradEngine` (nome/meta/tag/descrizione/riepilogo A11) + slug/limiti (A13, A14) + test di ripresa/idempotenza.
5. `TradWorker` (lotti, budget, lock, salute) + test (B4, B6).
6. Implementazioni PS reali (Db store, source repository su `ps_product_lang`), install/uninstall/upgrade, tabelle `ps_stktrad_*`.
   **Non collaudabili nel cloud**: scriverle con cura, lint, e marcarle "DA COLLAUDARE SU COPIA" in `docs/STATO.md`.
7. `TradApply` (marcia a secco, una lingua, registro, rollback) + export CSV.
8. Pagina BO + report + `README.md`/`PIANO.md` del modulo + guida d'uso breve.
Ogni fase si chiude con `docs/CHECKLIST-REVISIONE.md` (lint, rilettura, test avversari), poi commit e `docs/STATO.md` aggiornato. Domande bloccanti: chiederle all'utente all'inizio (vedi sotto), il resto usa il default.

## Modalità di lavoro attuale (2026-10-02)
Nessun collegamento a LibreTranslate o alla macchina locale: si scrive e si prova solo offline (PHPUnit, fake, server mock). Le prove reali arrivano dopo, in locale.

## Collaudo reale (lo fa l'utente in locale — mai in produzione)
Sulla macchina locale, sulla **copia gemella** del sito (stesso schema dei moduli precedenti: docker `tests/copia/`, porta dedicata) con LibreTranslate vero:
1. Installa il modulo (interruttore OFF), "Prova connessione", marcia a secco su ~50 prodotti, una lingua.
2. Ispezione a campione: codici intatti, HTML integro, nomi sensati, limiti rispettati. Confronto con l'output del legacy sulle stesse righe.
3. Applica su una lingua alla copia; verifica nel front. Solo dopo, e con conferma esplicita dell'utente, si valuta la produzione.

## Domande aperte (default raccomandato tra parentesi)
**Da porre all'utente all'inizio della sessione cloud (bloccanti):**
1. **Raggiungibilità di LibreTranslate dal sito**: gira su una macchina locale (WSL, GPU); il server di produzione non la raggiunge da solo.
   Opzioni: (a) tunnel SSH inverso dalla macchina locale verso il server mentre il worker gira; (b) worker che gira sulla macchina locale puntando al DB
   della **copia** o a un'API del modulo; (c) LibreTranslate su un host raggiungibile dal server. (default: il modulo vede solo "un URL configurabile" — scelta di rete rimandata al collaudo; non progettare niente che dipenda dalla soluzione.)
2. Separatore dei tag nell'import nativo e formato esatto (nel legacy `$` in output, virgola in input). (default: `$` configurabile; verificare su `AdminImportController` della copia).
3. Limiti lunghezza reali (default nella sezione requisiti 10).

**Con default, non bloccanti:**
4. Colonne/campi extra da tradurre (es. `ps_feature_value_lang`, categorie)? (default: NO, solo prodotto; da pianificare dopo).
5. Frasi tutte maiuscole: inviare maiuscolo o normalizzare? (default: configurabile, deciso in collaudo con il traduttore vero).
6. Lingua sorgente diversa da `it`? (default: no).
