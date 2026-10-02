# Trasferimento cloud ⇄ locale

## Fase 1 — lavoro in cloud (altra macchina)
1. Claude Desktop → nuova sessione **cloud** → collega il repo GitHub `inserzionista2simpletek-maker/traduzioni` (privato) → branch `main`
   (o `lavoro` se preferito).
2. Primo prompt suggerito, da incollare:

   > Leggi CLAUDE.md e i documenti che indica (SPEC, CONVENZIONI-MODULI-SIMPLETEK, ANALISI-BUG, STATO). Costruisci il modulo PrestaShop
   > `simpletektraduzioni` seguendo il "Piano a fasi" della SPEC, una fase alla volta, con test PHPUnit e commit per fase.
   > Prima fammi in un'unica volta le domande bloccanti della SPEC con il tuo default. Non hai accesso a PrestaShop, LibreTranslate né al catalogo:
   > motore puro testato offline; il guscio PS marcalo "DA COLLAUDARE SU COPIA". Non toccare la produzione.
   > A fine sessione aggiorna docs/STATO.md e fai push.

3. Se la sessione si interrompe: nuova sessione, stesso repo, stesso prompt — riparte da `docs/STATO.md`.
4. Non committare dati reali (`.gitignore` li esclude).

## Fase 2 — ritorno in locale (questa macchina)
```powershell
cd $env:USERPROFILE\Documents
git clone https://github.com/inserzionista2simpletek-maker/traduzioni.git traduci-catalogo-lavoro   # oppure: cd traduci-catalogo; git pull
cd traduci-catalogo-lavoro
composer install            # solo dev (phpunit); il modulo non ne ha bisogno in produzione
vendor\bin\phpunit
```
Poi seguire "Collaudo reale" in `docs/SPEC.md`: installazione del modulo sulla **copia gemella locale** (mai in produzione), LibreTranslate in WSL acceso, marcia a secco su ~50 prodotti.

Il file originale resta in `legacy/traduci_catalogo_gui.py` per confronto.

