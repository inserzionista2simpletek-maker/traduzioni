# Checklist di revisione (lavoro senza PrestaShop né LibreTranslate reali)

Decisione utente 2026-10-02: nessun collegamento a LibreTranslate né alla macchina locale durante la scrittura. Si scrive e si prova **solo offline**.
Questo non significa "senza test": il motore puro si prova con PHPUnit, fake e server mock. Non si fanno solo prove reali (PS, LibreTranslate, DB vero).
Poiché il guscio PrestaShop non è eseguibile nel cloud, **ogni fase si chiude con questa revisione**; il risultato va annotato in `docs/STATO.md`.

## Per ogni file PHP
1. `php -l` con la versione disponibile (e 8.1 / 8.3 se si riesce). Zero errori e zero warning.
2. Niente funzioni/sintassi oltre PHP 8.1 (no `readonly class`, no costanti tipizzate, no `#[\Override]`, ecc.).
3. Ogni nome di classe/metodo PrestaShop usato (`Db`, `Tools`, `Language`, `Configuration`, `Hook`, `Validate`, `pSQL`, `PrestaShopLogger`...):
   verificare di conoscerne con certezza firma e comportamento in PS 8.1.7. Se non si è certi: NON indovinare; isolare dietro un'interfaccia e scriverlo in `STATO.md` sotto "da verificare su copia".
4. Ogni query SQL: valori con `pSQL`/cast `(int)`, nome tabella con `_DB_PREFIX_`, niente `getValue`/`getRow` su `SHOW TABLES`, nessuna query senza limite su tabelle grandi, nessun caricamento dell'intero catalogo in memoria.
5. Nessuna scrittura sul catalogo fuori da `TradApply`; `TradApply` rispetta: marcia a secco, una sola `id_lang`, solo celle vuote salvo flag, registro delle modifiche.
6. Nessun file eseguibile raggiungibile dal web senza guardia; ogni cartella con `index.php`; lock solo in `sys_get_temp_dir()`.
7. Nessun segreto, IP, URL di produzione nel codice o nei test.

## Per ogni fase
8. Test PHPUnit verdi, inclusi casi avversari: stringa vuota, solo codici, HTML malformato, entità, UTF-8 multibyte, risposta del traduttore troncata/duplicata/mancante/in numero diverso dalle richieste, timeout, 5xx, 429.
9. Tentare di **violare** ogni garanzia dichiarata (es. "scrive una sola lingua", "non sovrascrive") con un test che ci prova; se riesce, correggere codice E documento.
10. Rilettura integrale del diff della fase, riga per riga, prima del commit. Se disponibile, un secondo passaggio con un subagent revisore indipendente (`/code-review`) con il brief: "trova difetti, non confermare".
11. `docs/ANALISI-BUG.md`: spuntare solo ciò che ha un test di regressione.

## Cosa NON dichiarare mai
- "Funziona" per codice non eseguito. Usare: «scritto, lint ok, non eseguito: da collaudare su copia».
- Nomi di colonne/tabelle PS non verificati come fatti: scriverli come ipotesi.

## Fine sessione
Elenco ordinato in `docs/STATO.md` § "Da collaudare su copia": per ciascuna voce, che cosa verificare e come (comando o schermata attesa), così che il collaudo locale sia una lista da spuntare.
