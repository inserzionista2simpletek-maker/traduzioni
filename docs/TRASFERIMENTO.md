# Trasferimento cloud ⇄ locale

## Fase 1 — lavoro in cloud (altra macchina)
1. Claude Desktop → nuova sessione **cloud** → collega il repo GitHub `traduci-catalogo` (privato) → branch `main`
   (o `lavoro` se preferito).
2. Primo prompt suggerito, da incollare:

   > Leggi CLAUDE.md, docs/SPEC.md e docs/ANALISI-BUG.md. Poi lavora il "Piano a fasi" della SPEC dalla fase 0
   > in avanti, una fase alla volta, con test e commit per fase. Per le domande aperte usa i default raccomandati
   > e annotali in docs/STATO.md. Non puoi accedere a LibreTranslate né al catalogo reale: usa FakeTranslator e dati sintetici.
   > A fine sessione aggiorna docs/STATO.md e fai push.

3. Se la sessione si interrompe: nuova sessione, stesso repo, stesso prompt — riparte da `docs/STATO.md`.
4. Non committare dati reali (`.gitignore` li esclude).

## Fase 2 — ritorno in locale (questa macchina)
```powershell
cd $env:USERPROFILE\Documents
git clone https://github.com/<utente>/traduci-catalogo.git traduci-catalogo-lavoro   # oppure: cd traduci-catalogo; git pull
cd traduci-catalogo-lavoro
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```
Poi seguire "Collaudo reale" in `docs/SPEC.md` (LibreTranslate in WSL acceso, estratto reale del catalogo, `--dry-run`, `--limit 50`).

Il file originale resta in `legacy/traduci_catalogo_gui.py` per confronto.
