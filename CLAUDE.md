# CLAUDE.md — traduci-catalogo

Leggi questo file per intero prima di fare qualunque cosa. Poi `docs/SPEC.md` e `docs/ANALISI-BUG.md`.

## Lingua
Rispondi SEMPRE in italiano (chat, commenti nel codice, commit, documentazione).

## Cos'è questo progetto
Strumento che traduce il catalogo prodotti di un e-shop PrestaShop (Simpletek) dall'italiano
in 7 lingue (en, fr, es, de, pt, pl, ro) usando **LibreTranslate** (self-hosted, GPU, in WSL
sulla macchina dell'utente). Input/output: un file Excel con un foglio `it` (sorgente) e un
foglio per lingua. L'output alimenta un import PHP in produzione (fuori da questo repo).

Il punto di partenza è `legacy/traduci_catalogo_gui.py`: uno script unico (~900 righe, GUI
tkinter) che funziona a tratti ma ha molti difetti (vedi `docs/ANALISI-BUG.md`).
**Obiettivo: riscriverlo bene come modulo pulito, testato, correggendo i difetti.**
`legacy/` resta SOLO come riferimento: non modificarlo e non farlo importare dal nuovo codice.

## Ambiente di lavoro (IMPORTANTE)
Si lavora in una sessione **cloud**: NON hai accesso a
- LibreTranslate reale (gira sulla macchina dell'utente, GPU/WSL)
- il catalogo reale (`traduzioni.xlsx`) né a PrestaShop né al DB di produzione

Quindi:
- Tutto deve essere sviluppabile e testabile **offline**: usa un traduttore finto
  (`FakeTranslator`, deterministico, es. prefisso `[en] ` + testo) e un generatore di Excel di
  esempio (`tools/make_sample_xlsx.py`) con dati sintetici (HTML, codici, maiuscolo, tag, duplicati,
  celle vuote, nomi uguali in tutte le lingue).
- Il motore deve dipendere da un'**interfaccia** `Translator` (metodo che traduce una LISTA di
  stringhe), con due implementazioni: `LibreTranslateClient` (HTTP reale) e `FakeTranslator`.
  Il client HTTP si testa con un server mock locale o con `responses`/`requests-mock`, mai in rete reale.
- Non inventare dati di catalogo, URL, chiavi o credenziali. Niente segreti nel repo.
- Repo privato: comunque NON committare mai `.xlsx`, `.db`, `.json` di output, log (vedi `.gitignore`).
  I dati di esempio sono solo quelli sintetici generati dallo script.

## Come lavorare
1. Prima di scrivere codice, leggi `docs/SPEC.md` e conferma/aggiorna il piano (sezione "Piano a fasi").
2. Sviluppa a fasi, un commit per fase con messaggio chiaro in italiano; test verdi prima di ogni commit.
3. Python >= 3.10 (sulla macchina locale c'è 3.14, Windows). Codice compatibile Windows (path con `pathlib`,
   niente comandi POSIX-only a runtime).
4. Test con `pytest`. Ogni bug di `docs/ANALISI-BUG.md` corretto deve avere un test di regressione
   e va spuntato nel file (`[x]`) con il riferimento del commit.
5. Stile: semplice, funzioni piccole, niente architetture inutili. Niente nuove dipendenze pesanti
   senza motivo: ammesse `requests`, `openpyxl`, `unidecode` (obbligatoria), `pytest`.
6. A fine sessione aggiorna `docs/STATO.md` (cosa fatto, cosa resta, decisioni prese, domande aperte)
   e pusha sul branch di lavoro. L'utente riprenderà il lavoro in locale clonando il repo
   (vedi `docs/TRASFERIMENTO.md`).

## Cose da NON fare
- Non toccare/riscrivere i dati reali, non assumere percorsi della macchina dell'utente: tutto
  configurabile (CLI/file di config), con default sensati.
- Non tradurre `sku`. Corrispondenza tra fogli SEMPRE per `sku`.
- Non fare scritture distruttive sul file Excel di input (vedi SPEC: input e output separati).
- Non aggiungere funzionalità non richieste in SPEC senza segnalarlo in `docs/STATO.md`.

## Decisioni aperte (da chiedere all'utente se bloccano)
Vedi sezione "Domande aperte" in `docs/SPEC.md`. Dove c'è un default raccomandato, usalo e annotalo
in `docs/STATO.md` invece di fermarti.
