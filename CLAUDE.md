# CLAUDE.md — simpletektraduzioni

Leggi questo file per intero prima di fare qualunque cosa. Poi, in ordine:
`docs/SPEC.md` → `docs/CONVENZIONI-MODULI-SIMPLETEK.md` → `docs/ANALISI-BUG.md` → `docs/STATO.md`.

## Lingua
Rispondi SEMPRE in italiano (chat, commenti nel codice, commit, documentazione).

## Cos'è questo progetto
Un **modulo custom PrestaShop 8.1.7** (`simpletektraduzioni`, PHP 8.1+) che traduce i testi dei prodotti dell'e-shop simpletek.net
dall'italiano in en, fr, es, de, pt, pl, ro con **LibreTranslate** (self-hosted dall'utente, GPU, in WSL sulla sua macchina).

Punto di partenza: `legacy/traduci_catalogo_gui.py`, uno script Python con GUI tkinter (~900 righe) che lavora su un Excel e ha molti difetti
(`docs/ANALISI-BUG.md`). **Obiettivo: portarne i comportamenti buoni in un modulo PrestaShop pulito, testato, che corregga i difetti.**
`legacy/` è solo riferimento: non modificarlo.

## Ambiente di lavoro (IMPORTANTE)
Lavori in una sessione **cloud**. Non hai accesso a: PrestaShop, DB, il server di produzione, LibreTranslate reale, il catalogo reale.
Quindi:
- Il **motore** (protezione testo, stati, cache, worker, slug, applicazione) è PHP **puro, senza classi PrestaShop**, testabile con **PHPUnit**
  nel cloud, con traduttore finto (`TradFakeTranslator`), repository in-memory e un server HTTP mock locale (`php -S`) per il client.
- Il **guscio PrestaShop** (install, tabelle, hook, pagina BO, store su DB, lettura `ps_product_lang`) lo scrivi senza poterlo eseguire:
  fai `php -l` (8.1 e 8.3 se disponibili), rileggilo due volte, e marcalo in `docs/STATO.md` come **«DA COLLAUDARE SU COPIA»**.
  Non dichiarare mai "funziona" per ciò che non hai potuto eseguire.
- Se PHP/Composer non sono nell'ambiente: installali (apt/curl) e annota la versione in `STATO.md`. Se proprio non si può, dillo all'utente.
- Non inventare dati di catalogo, URL, chiavi, nomi di tabelle PS che non conosci con certezza (se non sei sicuro dello schema di
  `ps_product_lang`/`ps_tag`/`ps_product_tag`, scrivilo come ipotesi in STATO e fallo verificare all'utente in locale).
- Repo (anche se privato): **mai** credenziali, IP, chiavi, `.xlsx`/`.db`/log. I dati di prova sono sintetici.

## Come lavorare
1. All'inizio **fai all'utente le domande bloccanti** della SPEC (§ Domande aperte, punti 1-3), in un'unica volta, proponendo il default. Poi procedi.
2. Lavora il "Piano a fasi" della SPEC, una fase alla volta: test verdi → commit in italiano → aggiorna `docs/STATO.md`.
3. Ogni difetto di `docs/ANALISI-BUG.md` corretto: test di regressione + spunta `[x]` con riferimento al commit.
4. Pattern SimpleTek obbligatori (interruttore OFF, marcia a secco ON, motore puro, hook canonici, lock fuori dal modulo, tetti espliciti…): vedi `docs/CONVENZIONI-MODULI-SIMPLETEK.md`.
5. Semplice > ingegnoso. Funzioni piccole, commenti che spiegano il perché. Niente dipendenze a runtime in produzione (niente `vendor/` necessario al modulo).
6. A fine sessione: `docs/STATO.md` aggiornato (fatto / resta / decisioni / da collaudare / domande) e push. L'utente riprenderà in locale (`docs/TRASFERIMENTO.md`).

## Cose da NON fare
- Non scrivere nulla che tocchi la produzione, nemmeno come script "da lanciare": tutto passa dal collaudo su copia locale e dalla conferma esplicita dell'utente.
- Il modulo non scrive nel catalogo durante la traduzione: staging → revisione → applicazione esplicita (SPEC, "Principio di sicurezza centrale").
- Non tradurre `reference`/`sku`. Non modificare il rapporto Danea↔PrestaShop né altro del sito: il modulo è aggiuntivo.
- Non riaccendere/accendere l'interruttore da codice. Non cancellare le traduzioni applicate alla disinstallazione.
- Non aggiungere funzionalità fuori SPEC senza segnalarlo in `docs/STATO.md`.
