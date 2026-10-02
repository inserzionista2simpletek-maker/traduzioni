# Convenzioni dei moduli custom SimpleTek (estratto per la sessione cloud)

Distillato da `CONOSCENZA-SERVER.md` del repo privato dei moduli (non accessibile dal cloud) e dal modulo di riferimento
`simpletekscontoqta`. **Nessuna credenziale qui, e non deve mai entrarne.** Se un'informazione non c'è, chiedila all'utente: non inventarla.

## Ambiente di produzione (fatti verificati)
- PrestaShop **8.1.7**; **PHP web 8.1 (FPM)**, **PHP CLI dei cron 8.3**. Codice compatibile 8.1+, lint con entrambe le versioni.
- MariaDB, tabelle InnoDB (`_MYSQL_ENGINE_`). Timezone Europe/Rome ovunque.
- Tema custom (`orange-theme-8`). Il server è dietro **nginx (Plesk)**, che **scavalca gli `.htaccess` per certe estensioni**:
  una cartella di modulo è pubblica. Quindi: file eseguibili solo-CLI con guardia `if (PHP_SAPI !== 'cli') { exit; }`,
  ogni `index.php` di protezione nelle cartelle, niente dati sensibili dentro la cartella del modulo.

## Struttura e naming
- Nome tecnico `simpletek<qualcosa>` (qui: `simpletektraduzioni`), classe `Simpletektraduzioni`, prefisso classi `Trad*`, tabelle `ps_stktrad_*`.
- `$this->tab = 'personalizzati'; $this->author = 'SimpleTek'; $this->need_instance = 0; $this->bootstrap = true;`
  `ps_versions_compliancy = ['min' => '1.7.0.0', 'max' => _PS_VERSION_]`.
- Ogni file PHP del modulo inizia con `if (!defined('_PS_VERSION_')) { exit; }` (le classi del **motore puro** no: devono girare nei test; proteggerle dalla cartella pubblica con la guardia di
  `PHP_SAPI`/costante definita dal guscio, come fa `simpletekscontoqta`).
- Commenti in italiano; docblock che spiega il PERCHÉ. Ogni modulo ha `README.md` (com'è fatto), `PIANO.md` (perché e misure), `LEGGIMI-PRIMA.md` (ingresso rapido).

## Pattern obbligatori
- **Interruttore generale SPENTO di default**: installare non cambia nulla di ciò che vedono i clienti; ON/OFF solo dall'utente nel BO; mai riaccenderlo da codice.
- **Marcia a secco ACCESA di default** per le azioni che scrivono sul catalogo.
- **Motore puro + guscio sottile**: la logica sta in classi senza PrestaShop (testabili offline), il modulo aggancia hook/BO.
- **Hook: registrare solo nomi CANONICI** (`action…`/`display…`), mai alias. Guardia di sanità che confronta registrazione reale e attesa.
- **Worker/cron**: lock `flock` in `sys_get_temp_dir()` (MAI nella cartella del modulo: i deploy la sostituiscono); budget di tempo, uscita pulita;
  con modulo OFF aggiornare solo il timestamp di salute. Preload dei moduli con override se necessario (non pertinente qui salvo indicazioni).
- **Upgrade da CLI**: `Module::initUpgradeModule` non scatta senza contesto admin; il file `upgrade/upgrade-X.Y.Z.php` espone `upgrade_module_X_Y_Z($module)`.
- **SQL**: `pSQL($testo, true)` per testi multilinea; `SHOW TABLES` con `executeS` (getValue/getRow aggiungono LIMIT e fanno errore su MariaDB);
  nessuna query che carichi l'intero catalogo in memoria; scritture a lotti in transazione dove serve.
- **Mai** `getOrderTotal(false, ONLY_DISCOUNTS/BOTH)` (non pertinente qui, ma vale sul sito).
- **Tab admin di servizio** (solo endpoint AJAX): `id_parent = -1`.
- **Tutto ciò che deve sopravvivere al deploy sta FUORI dalla cartella del modulo** (upload, lock, tabelle). Deploy = swap atomico, non sovrascrittura.
- **Dati di terzi**: tetti espliciti (lunghezze, numero righe per lotto, dimensione risposta) — validare ogni input e ogni risposta del traduttore.
- **Token/chiavi mai in query string**; l'endpoint può rispondere 200 anche quando rifiuta: controllare il corpo.
- **Input utente nelle mail**: `strip_tags` + collasso whitespace.
- **Traduzioni delle stringhe del modulo**: usare `$this->l()` e fornire almeno it (e en se possibile).

## Metodo di collaudo (obbligatorio)
- Collaudare il **percorso reale del core**, non solo le funzioni interne: un test che non passa dal punto in cui PrestaShop entra nel tuo codice non prova che funzioni.
- Se il codice o il documento dichiara una garanzia ("non scrive mai X", "solo una lingua", "sola lettura"), **provare a violarla**; se la violazione riesce, correggere codice e documento.
- Provare a ingannare il modulo, non solo a romperlo (input sporchi, HTML malformato, risposte incomplete del traduttore, dati cambiati a metà run).
- Il collaudo sul sito vero si fa su una **copia gemella locale**; **in produzione non si scrive niente senza autorizzazione esplicita dell'utente** (vale anche per i test).
- Hook da CLI: il dispatcher Symfony scarta tutto senza employee: per collaudare gli hook da CLI serve un contesto employee simulato.

## Contesto d'uso dei testi (dal processo reale dell'utente)
- Il catalogo nasce da **Danea (fonte)** e viene aggiornato con l'import nativo di PrestaShop; l'utente importa **una lingua per volta** e vuole che si scriva
  **solo su quell'`id_lang`**. Non toccare il rapporto Danea↔PrestaShop né altro del sito: il modulo è **aggiuntivo**.
- Formati dell'import nativo: feature con `$` tra feature e `:` tra nome e valore; immagini fuori scopo qui.
- Molti prodotti sono varianti quasi identiche: testi ripetuti → la cache per (testo, lingua) è importante.
