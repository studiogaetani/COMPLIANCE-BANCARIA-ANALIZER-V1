# 🏦 Compliance Bancaria Analyzer

**Strumento professionale per dottori commercialisti e revisori legali.**

Analisi automatica delle anomalie tra estratti conto bancari e corrispettivi/ricavi dichiarati, 
ai fini della prevenzione delle lettere di compliance dell'Agenzia delle Entrate.

---

## 🚀 Deploy rapido su Streamlit Cloud

### 1. Fork / carica su GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/TUO-USERNAME/compliance-bancaria.git
git push -u origin main
```

### 2. Deploy su Streamlit Cloud
1. Vai su **[share.streamlit.io](https://share.streamlit.io)**
2. Clicca **"New app"**
3. Seleziona il tuo repository GitHub
4. **Main file path:** `app.py`
5. Clicca **"Deploy!"**

L'app sarà online in circa 2-3 minuti, completamente gratuita.

---

## 📁 Struttura del progetto

```
compliance_app/
├── app.py              ← App principale Streamlit
├── requirements.txt    ← Dipendenze Python
└── README.md           ← Questa guida
```

---

## 🔍 Funzionalità

| Funzione | Descrizione |
|----------|-------------|
| **Caricamento file** | Supporta .xlsx, .xls, .csv per estratti conto e corrispettivi |
| **Rilevamento automatico colonne** | Riconosce nomi di colonne in italiano e inglese |
| **6 tipologie di anomalie** | Versamenti anomali, prelievi non identificabili, delta ricavi, cifre tonde, concentrazione, giornate anomale |
| **Indice di rischio** | Score 0-100% con soglie Basso/Medio/Alto |
| **Giustificazioni normative** | Per ogni anomalia, riferimenti a norme e possibili documentazioni difensive |
| **Export Excel + CSV** | Download report con tutti i dati analizzati |

---

## 📋 Formato file supportati

### Estratto conto bancario
Colonne riconosciute automaticamente:
- **Data**: `data`, `date`, `valuta`, `data operazione`
- **Descrizione**: `descrizione`, `causale`, `description`, `operazione`
- **Entrate**: `avere`, `accredito`, `credito`, `entrate`, `credit`
- **Uscite**: `dare`, `addebito`, `debito`, `uscite`, `debit`
- **Importo unico**: `importo`, `amount` (con segno +/-)

### Registro corrispettivi / fatture
Colonne riconosciute automaticamente:
- **Data**: `data`, `date`, `competenza`, `data fattura`
- **Imponibile**: `imponibile`, `ricavo`, `totale`, `corrispettivo`, `fatturato`, `importo`
- **IVA**: `iva`, `vat`, `imposta` (opzionale)

---

## ⚖️ Riferimenti normativi

- Art. 32 D.P.R. n. 600/1973 — Indagini finanziarie imposte dirette
- Art. 51 D.P.R. n. 633/1972 — Indagini finanziarie IVA
- Art. 7 D.P.R. n. 605/1973 — Anagrafe dei rapporti finanziari
- L. n. 212/2000 — Statuto del Contribuente
- D.Lgs. n. 218/1997 — Accertamento con adesione
- D.Lgs. n. 471/1997 — Sanzioni amministrative tributarie
- D.Lgs. n. 472/1997, art. 13 — Ravvedimento operoso
- D.Lgs. n. 74/2000 — Reati tributari
- D.Lgs. n. 87/2024 — Riforma sistema sanzionatorio
- Corte Cost. n. 228/2014 — Presunzioni bancarie lavoratori autonomi
- Cass. SS.UU. n. 26635/2009 — Onere della prova indagini finanziarie

---

## ⚠️ Disclaimer

Strumento indicativo per uso professionale. Non sostituisce la consulenza di un dottore commercialista.
I risultati devono essere verificati caso per caso alla luce della documentazione contabile completa.
