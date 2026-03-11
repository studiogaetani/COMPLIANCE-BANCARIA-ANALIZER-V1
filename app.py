"""
Compliance Bancaria Analyzer
============================
Analisi anomalie tra estratti conto bancari e corrispettivi/ricavi dichiarati.
Prevenzione lettere di compliance dell'Agenzia delle Entrate.

Autore: generato con Claude (Anthropic) — uso professionale per dottori commercialisti
"""

import streamlit as st
import pandas as pd
import numpy as np
import io
import re
from datetime import datetime

# PDF support (pdfplumber)
try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# OCR support (per estratti conto con font proprietari)
try:
    import fitz  # pymupdf
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG PAGINA
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Compliance Bancaria Analyzer",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# CSS PERSONALIZZATO
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Font & sfondo */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .main { background-color: #F0F4FA; }

    /* Nasconde il menu hamburger e footer Streamlit */
    #MainMenu, footer { visibility: hidden; }

    /* Metriche personalizzate */
    div[data-testid="metric-container"] {
        background-color: #ffffff;
        border: 1px solid #D0DCF0;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 2px 8px rgba(27,58,107,0.07);
    }
    div[data-testid="metric-container"] label {
        color: #1B3A6B !important;
        font-weight: 700 !important;
        font-size: 12px !important;
        text-transform: uppercase;
        letter-spacing: 0.8px;
    }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
        font-size: 24px !important;
        font-weight: 800 !important;
    }

    /* Box colorati */
    .box-alto    { background:#FFF0F2; border-left:5px solid #C8102E; border-radius:10px; padding:16px 20px; margin:10px 0; }
    .box-medio   { background:#FFFBF0; border-left:5px solid #E8A020; border-radius:10px; padding:16px 20px; margin:10px 0; }
    .box-basso   { background:#F0FBF6; border-left:5px solid #1A7F5A; border-radius:10px; padding:16px 20px; margin:10px 0; }
    .box-info    { background:#EBF0F8; border-left:5px solid #2E5FA3; border-radius:10px; padding:16px 20px; margin:10px 0; }
    .box-warning { background:#FFFBF0; border-left:5px solid #E8A020; border-radius:10px; padding:12px 18px; margin:8px 0; }

    /* Header app */
    .app-header {
        background: linear-gradient(135deg, #1B3A6B 0%, #2E5FA3 100%);
        color: white;
        padding: 28px 36px;
        border-radius: 16px;
        margin-bottom: 28px;
    }
    .app-header h1 { color: white; margin: 0; font-size: 26px; font-weight: 900; }
    .app-header p  { color: #C0D0E8; margin: 6px 0 0; font-size: 14px; }

    /* Badge gravità */
    .badge-alta   { background:#C8102E; color:white; border-radius:6px; padding:2px 10px; font-size:11px; font-weight:800; letter-spacing:1px; }
    .badge-media  { background:#E8A020; color:white; border-radius:6px; padding:2px 10px; font-size:11px; font-weight:800; letter-spacing:1px; }
    .badge-bassa  { background:#1A7F5A; color:white; border-radius:6px; padding:2px 10px; font-size:11px; font-weight:800; letter-spacing:1px; }

    /* Tabelle */
    .dataframe thead th { background-color: #1B3A6B !important; color: white !important; font-weight: 700 !important; }
    .dataframe tbody tr:nth-child(even) { background-color: #F0F4FA; }

    /* Sidebar */
    section[data-testid="stSidebar"] { background-color: #1B3A6B; }
    section[data-testid="stSidebar"] * { color: #E8EFF8 !important; }
    section[data-testid="stSidebar"] .stMarkdown h2,
    section[data-testid="stSidebar"] .stMarkdown h3 { color: #ffffff !important; font-weight: 800; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONI DI PARSING
# ─────────────────────────────────────────────────────────────────────────────

def normalizza_colonna(col: str) -> str:
    """Normalizza il nome della colonna per il rilevamento automatico."""
    return str(col).lower().strip().replace(".", "").replace("/", "").replace("_", " ")


def trova_colonna(df: pd.DataFrame, keywords: list) -> str | None:
    """Trova la prima colonna che contiene una delle keyword (case-insensitive)."""
    for col in df.columns:
        norm = normalizza_colonna(col)
        for kw in keywords:
            if kw.lower() in norm:
                return col
    return None


def parse_importo(val) -> float:
    """Converte valori monetari in float, gestendo formati italiani ed europei."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    s = re.sub(r"[€$\s]", "", s)
    # formato italiano: 1.234,56 → 1234.56
    if re.search(r"\d\.\d{3},", s):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    elif "," in s and "." in s:
        # es. 1,234.56
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0



# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONI DI PARSING PDF — PARSER SPECIFICI PER FORMATO REALE
# ─────────────────────────────────────────────────────────────────────────────

def _parse_amt_it(s: str) -> float:
    """Converte stringa importo italiano (1.234,56) in float."""
    s = str(s).strip()
    if re.match(r"^\d{1,3}(\.\d{3})*,\d{2}$", s):
        return float(s.replace(".", "").replace(",", "."))
    return 0.0


def parse_corrispettivi_pdf(file_bytes: bytes) -> pd.DataFrame | None:
    """
    Parser per Registro dei Corrispettivi (formato software gestionale).
    Struttura per riga:
      - Y riga 1: [x≈23] DD/MM/YYYYVendite [x≈89] giornaliere [x≈350-370] importo
      - Y riga 2: [x≈400-410] importo_ripetuto  [x≈489] codice_IVA
    Pagine RIEPILOGO (totali trimestrali) vengono saltate.
    Calcola imponibile e IVA dal totale corrispettivo (IVA inclusa).
    """
    if not PDF_AVAILABLE:
        st.error("❌ pdfplumber non installato. Aggiungere 'pdfplumber' a requirements.txt")
        return None

    IVA_RATES = {"10": 10.0, "34": 22.0, "22": 22.0, "4": 4.0}
    DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})")
    AMT_RE  = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2}$")
    rows = []

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                raw = page.extract_text() or ""
                if "RIEPILOGO" in raw.upper():
                    continue  # skip summary pages

                words = page.extract_words(x_tolerance=5, y_tolerance=4)
                by_y = {}
                for w in words:
                    y = round(w["top"] / 2) * 2
                    by_y.setdefault(y, []).append(w)

                sorted_ys = sorted(by_y.keys())
                for idx, y in enumerate(sorted_ys):
                    row_words = sorted(by_y[y], key=lambda w: w["x0"])
                    if not row_words:
                        continue

                    first_text = row_words[0]["text"]
                    date_m = DATE_RE.match(first_text)
                    if not date_m:
                        continue
                    data = date_m.group(1)

                    # Amount: first word with x > 300 that looks like an amount
                    amt_words = [w for w in row_words
                                 if w["x0"] > 300 and AMT_RE.match(w["text"])]
                    if not amt_words:
                        continue
                    totale = _parse_amt_it(min(amt_words, key=lambda w: w["x0"])["text"])

                    # Description: everything between date end and amount col
                    non_date = first_text[len(date_m.group(0)):]
                    extra = [w["text"] for w in row_words
                             if w["x0"] > 20 and w["x0"] < 300 and w["text"] != first_text]
                    descrizione = " ".join(p for p in ([non_date] + extra) if p.strip())                                   or "Vendite giornaliere"

                    # IVA code from next Y row (at x ≈ 489)
                    iva_code = None
                    if idx + 1 < len(sorted_ys):
                        next_ws = sorted(by_y[sorted_ys[idx + 1]], key=lambda w: w["x0"])
                        iva_cands = [w for w in next_ws
                                     if w["x0"] > 460 and w["text"].isdigit()]
                        if iva_cands:
                            iva_code = iva_cands[0]["text"]

                    rate = IVA_RATES.get(iva_code, 10.0) / 100.0
                    imponibile = round(totale / (1 + rate), 2)
                    iva = round(totale - imponibile, 2)

                    rows.append({
                        "data": data,
                        "descrizione": descrizione,
                        "imponibile": imponibile,
                        "iva": iva,
                        "totale_corrispettivo": totale,
                        "aliquota_iva_pct": IVA_RATES.get(iva_code, 10.0),
                    })
    except Exception as e:
        st.error(f"Errore lettura PDF corrispettivi: {e}")
        return None

    if not rows:
        return None
    df = pd.DataFrame(rows).drop_duplicates(subset=["data", "totale_corrispettivo"])
    return df if not df.empty else None


def parse_banca_intesa_pdf(file_bytes: bytes) -> pd.DataFrame | None:
    """
    Parser per estratto conto Banca Intesa Sanpaolo con OCR.

    Il PDF usa un font proprietario con encoding custom (PUA Unicode ue0xx),
    quindi pdfplumber non può estrarre testo leggibile. Si usa OCR via
    PyMuPDF + Tesseract (image_to_string) che legge correttamente tutte le righe.

    Logica:
    - Ogni riga che inizia con DD.MM.YYYY  DD.MM.YYYY  è un movimento
    - L'asterisco (*) a inizio descrizione indica un addebito
    - L'ultimo importo trovato nella riga/blocco è il valore del movimento
    """
    if not OCR_AVAILABLE:
        st.error(
            "❌ OCR non disponibile. Installare: pymupdf, pytesseract, pillow "
            "e tesseract-ocr (con lingua italiana)."
        )
        return None

    DATE_LINE_RE = re.compile(r"^(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})\s+(.+)")
    AMT_RE = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")
    rows = []

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        total_pages = len(doc)
        prog = st.progress(0, text="OCR in corso…")

        all_lines = []

        for page_idx in range(total_pages):
            prog.progress(
                int((page_idx + 1) / total_pages * 100),
                text=f"OCR pagina {page_idx + 1}/{total_pages}…"
            )
            page_obj = doc[page_idx]
            mat = fitz.Matrix(2.5, 2.5)
            pix = page_obj.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text = pytesseract.image_to_string(img, lang="ita", config="--psm 6")
            all_lines.extend(text.split("\n"))

        prog.empty()
        doc.close()

        # ── Scansione righe ────────────────────────────────────────────────
        i = 0
        while i < len(all_lines):
            line = all_lines[i].strip()
            m = DATE_LINE_RE.match(line)
            if m:
                data_op  = m.group(1)
                desc_raw = m.group(3)
                is_addebito = desc_raw.lstrip().startswith("*")

                # Accumula importi e descrizione su righe successive
                amounts = AMT_RE.findall(desc_raw)
                desc_parts = [AMT_RE.sub("", desc_raw).strip()]

                j = i + 1
                while j < len(all_lines):
                    nxt = all_lines[j].strip()
                    # Ferma se inizia una nuova transazione o una riga header
                    if DATE_LINE_RE.match(nxt):
                        break
                    if re.match(r"^(Data Opera|Saldo|INTESA|Totali\b)", nxt, re.I):
                        break
                    more = AMT_RE.findall(nxt)
                    amounts.extend(more)
                    clean = AMT_RE.sub("", nxt).strip()
                    if clean:
                        desc_parts.append(clean)
                    j += 1

                # Prendi l'ultimo importo trovato come valore del movimento
                importo = 0.0
                if amounts:
                    raw = amounts[-1].replace(".", "").replace(",", ".")
                    try:
                        importo = float(raw)
                    except ValueError:
                        pass

                if importo > 0:
                    descrizione = " ".join(p for p in desc_parts if p)[:100]
                    rows.append({
                        "data":        data_op,
                        "descrizione": descrizione,
                        "entrata":     0.0 if is_addebito else importo,
                        "uscita":      importo if is_addebito else 0.0,
                    })
                i = j
            else:
                i += 1

    except Exception as e:
        st.error(f"Errore OCR PDF banca: {e}")
        return None

    if not rows:
        st.warning("⚠️ Nessun movimento trovato nell'estratto conto. "
                   "Verificare che il PDF contenga la sezione 'Dettaglio movimenti'.")
        return None

    df = pd.DataFrame(rows)
    df = df[(df["entrata"] > 0) | (df["uscita"] > 0)].reset_index(drop=True)
    return df if not df.empty else None


def carica_pdf_automatico(file_bytes: bytes, filename: str) -> tuple:
    """
    Determina automaticamente se il PDF è un estratto conto o corrispettivi
    e chiama il parser appropriato.
    Ritorna (tipo, DataFrame) dove tipo è 'banca' o 'corr'.
    """
    # Prima prova OCR per capire il tipo (testo leggibile anche con font custom)
    try:
        if OCR_AVAILABLE:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            mat = fitz.Matrix(100 / 72, 100 / 72)
            pix = doc[0].get_pixmap(matrix=mat)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            first_text = pytesseract.image_to_string(img, lang="ita").upper()
            doc.close()
        elif PDF_AVAILABLE:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                first_text = (pdf.pages[0].extract_text() or "").upper()
        else:
            return "unknown", None

        if "CORRISPETTIVI" in first_text or "IMPONIBILE" in first_text:
            return "corr", parse_corrispettivi_pdf(file_bytes)
        else:
            return "banca", parse_banca_intesa_pdf(file_bytes)
    except Exception:
        return "unknown", None


def carica_estratto_conto(file) -> pd.DataFrame | None:
    """
    Legge un estratto conto bancario in formato Excel o CSV.
    Riconosce automaticamente le colonne data, descrizione, entrate, uscite.
    """
    try:
        fname = getattr(file, "name", "") or ""
        if fname.lower().endswith(".csv"):
            # prova separatori diversi
            for sep in [";", ",", "\t", "|"]:
                try:
                    df = pd.read_csv(file, sep=sep, dtype=str, encoding="utf-8-sig")
                    if len(df.columns) >= 2:
                        break
                except Exception:
                    file.seek(0)
                    continue
        else:
            df = pd.read_excel(file, dtype=str)

        if df.empty:
            return None

        # Rilevamento colonne
        col_data   = trova_colonna(df, ["data", "date", "valuta", "value date", "data operazione", "data val"])
        col_descr  = trova_colonna(df, ["descrizione", "causale", "description", "operazione", "dettaglio", "note", "wording"])
        col_entrata= trova_colonna(df, ["avere", "entrate", "accredito", "credito", "credit", "versamento", "dare +", "importo avere"])
        col_uscita = trova_colonna(df, ["dare", "uscite", "addebito", "debito", "debit", "prelievo", "importo dare"])
        col_importo= trova_colonna(df, ["importo", "amount", "movimento", "saldo movimento", "valore"])

        result = pd.DataFrame()

        result["data"]       = df[col_data].fillna("") if col_data else ""
        result["descrizione"]= df[col_descr].fillna("") if col_descr else ""

        if col_entrata and col_uscita:
            result["entrata"] = df[col_entrata].apply(parse_importo).abs()
            result["uscita"]  = df[col_uscita].apply(parse_importo).abs()
        elif col_importo:
            importi = df[col_importo].apply(parse_importo)
            result["entrata"] = importi.clip(lower=0)
            result["uscita"]  = (-importi).clip(lower=0)
        else:
            # fallback: prende la prima colonna numerica
            num_cols = [c for c in df.columns if df[c].apply(parse_importo).sum() != 0]
            if num_cols:
                importi = df[num_cols[0]].apply(parse_importo)
                result["entrata"] = importi.clip(lower=0)
                result["uscita"]  = (-importi).clip(lower=0)
            else:
                return None

        # Rimuovi righe vuote
        result = result[(result["entrata"] > 0) | (result["uscita"] > 0)].reset_index(drop=True)
        return result if not result.empty else None

    except Exception as e:
        st.error(f"Errore lettura estratto conto: {e}")
        return None


def carica_corrispettivi(file) -> pd.DataFrame | None:
    """
    Legge un registro corrispettivi / fatture attive in formato Excel o CSV.
    Riconosce automaticamente le colonne data, imponibile, IVA.
    """
    try:
        fname = getattr(file, "name", "") or ""
        if fname.lower().endswith(".csv"):
            for sep in [";", ",", "\t", "|"]:
                try:
                    df = pd.read_csv(file, sep=sep, dtype=str, encoding="utf-8-sig")
                    if len(df.columns) >= 2:
                        break
                except Exception:
                    file.seek(0)
                    continue
        else:
            df = pd.read_excel(file, dtype=str)

        if df.empty:
            return None

        col_data    = trova_colonna(df, ["data", "date", "competenza", "data emissione", "data fattura"])
        col_descr   = trova_colonna(df, ["descrizione", "causale", "note", "prodotto", "servizio", "cliente"])
        col_imponi  = trova_colonna(df, ["imponibile", "ricavo", "ricavi", "totale", "corrispettivo",
                                         "fatturato", "vendite", "amount", "incasso", "importo", "netto"])
        col_iva     = trova_colonna(df, ["iva", "vat", "imposta", "tax"])

        if not col_imponi:
            return None

        result = pd.DataFrame()
        result["data"]        = df[col_data].fillna("") if col_data else ""
        result["descrizione"] = df[col_descr].fillna("") if col_descr else ""
        result["imponibile"]  = df[col_imponi].apply(parse_importo).abs()
        result["iva"]         = df[col_iva].apply(parse_importo).abs() if col_iva else 0.0

        result = result[result["imponibile"] > 0].reset_index(drop=True)
        return result if not result.empty else None

    except Exception as e:
        st.error(f"Errore lettura corrispettivi: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# FUNZIONE DI ANALISI
# ─────────────────────────────────────────────────────────────────────────────

def analizza(banca: pd.DataFrame, corr: pd.DataFrame) -> dict:
    """Calcola tutte le metriche e individua le anomalie."""

    tot_entrate  = banca["entrata"].sum()
    tot_uscite   = banca["uscita"].sum()
    tot_ricavi   = corr["imponibile"].sum()
    tot_iva      = corr["iva"].sum()
    tot_fatturato= tot_ricavi + tot_iva

    delta        = tot_entrate - tot_fatturato
    delta_pct    = abs(delta) / tot_fatturato * 100 if tot_fatturato > 0 else 0

    anomalie = []

    # ── 1. Versamenti anomali per importo ────────────────────────────────────
    entrate_pos = banca[banca["entrata"] > 0]
    if not entrate_pos.empty:
        media_gg = entrate_pos["entrata"].mean()
        soglia   = media_gg * 3
        grandi   = banca[(banca["entrata"] > soglia) & (banca["entrata"] > 5000)].copy()
        if not grandi.empty:
            anomalie.append({
                "tipo"    : "Versamenti anomali per importo",
                "gravita" : "ALTA",
                "count"   : len(grandi),
                "totale"  : grandi["entrata"].sum(),
                "descr"   : (f"{len(grandi)} versamenti superiori a 3× la media per operazione "
                             f"(soglia: {media_gg*3:,.2f}€). Potrebbero essere contestati come ricavi occulti."),
                "df"      : grandi.head(10),
                "giustif" : ("Documentare con: fatture di importo rilevante già dichiarate, "
                             "contratti di finanziamento soci (con data certa), verbali assembleari, "
                             "estratti conto di altri conti (girofondi), rimborsi assicurativi, "
                             "contributi pubblici o cessioni di beni strumentali."),
                "norma"   : "Art. 32 co. 1 n. 2 D.P.R. 600/1973 — presunzione di ricavo sui versamenti non giustificati",
            })

    # ── 2. Prelievi rilevanti non identificabili ─────────────────────────────
    pattern_ok = r"stipend|f24|imposte|iva|inps|inail|fornitor|salary|tax|pagament|tribut|contrib|affitt|mutuo|leasing"
    grandi_prel = banca[
        (banca["uscita"] > 3000) &
        (~banca["descrizione"].str.lower().str.contains(pattern_ok, na=False))
    ].copy()
    if not grandi_prel.empty:
        anomalie.append({
            "tipo"    : "Prelevamenti rilevanti non identificabili",
            "gravita" : "MEDIA",
            "count"   : len(grandi_prel),
            "totale"  : grandi_prel["uscita"].sum(),
            "descr"   : (f"{len(grandi_prel)} addebiti superiori a 3.000€ privi di causale "
                         "riconducibile a spese ordinarie (stipendi, F24, fornitori, affitti)."),
            "df"      : grandi_prel.head(10),
            "giustif" : ("Documentare con: fatture passive del fornitore, ricevute di pagamento, "
                         "registro di cassa (per prelievi alimentati dalla cassa aziendale), "
                         "contratti di restituzione prestiti, estratti conto personali del titolare."),
            "norma"   : "Art. 32 co. 1 n. 2 D.P.R. 600/1973 — i prelievi si presumono acquisti in nero (solo imprese)",
        })

    # ── 3. Delta entrate vs fatturato ────────────────────────────────────────
    if abs(delta) > 1000:
        grav = "ALTA" if delta_pct > 20 else "MEDIA" if delta_pct > 10 else "BASSA"
        anomalie.append({
            "tipo"    : "Delta entrate bancarie vs fatturato dichiarato" if delta > 0 else "Ricavi dichiarati eccedenti le entrate bancarie",
            "gravita" : grav,
            "count"   : 1,
            "totale"  : abs(delta),
            "descr"   : (f"Differenza di {abs(delta):,.2f}€ ({delta_pct:.1f}%) tra totale entrate bancarie "
                         f"({tot_entrate:,.2f}€) e fatturato dichiarato ({tot_fatturato:,.2f}€). "
                         + ("Le entrate eccedono il dichiarato: rischio presunzione di ricavi occulti." if delta > 0
                            else "I ricavi dichiarati eccedono le entrate: verificare incassi non ancora accreditati.")),
            "df"      : pd.DataFrame(),
            "giustif" : ("Per entrate > dichiarato: finanziamenti soci, girofondi, rimborsi, contributi pubblici. "
                         "Per dichiarato > entrate: crediti commerciali non ancora incassati, "
                         "ricavi per competenza registrati ma non ancora accreditati in banca."),
            "norma"   : "Circ. AdE n. 6/E 2023 — confronto automatizzato estratti conto vs dichiarazioni",
        })

    # ── 4. Versamenti in cifra tonda (possibile contante) ───────────────────
    tondi = banca[
        (banca["entrata"] >= 1000) &
        (banca["entrata"] <= 50000) &
        (banca["entrata"] % 500 == 0)
    ].copy()
    if len(tondi) > 2:
        anomalie.append({
            "tipo"    : "Versamenti in cifra tonda (possibile contante)",
            "gravita" : "MEDIA",
            "count"   : len(tondi),
            "totale"  : tondi["entrata"].sum(),
            "descr"   : (f"{len(tondi)} versamenti in cifra esattamente multipla di 500€ "
                         f"(range 1.000–50.000€). Potrebbero indicare incassi in contante non tracciati."),
            "df"      : tondi.head(10),
            "giustif" : ("Documentare la provenienza di ogni versamento in contante: "
                         "registro di cassa aggiornato, ricevute fiscali/corrispettivi del giorno corrispondente, "
                         "estratto conto della cassa aziendale."),
            "norma"   : "D.Lgs. 231/2007 art. 49 — limitazioni all'uso del contante; art. 32 D.P.R. 600/1973",
        })

    # ── 5. Giorni con molti movimenti in entrata ─────────────────────────────
    entrate_df = banca[banca["entrata"] > 0].copy()
    if not entrate_df.empty and entrate_df["data"].str.len().gt(0).any():
        conti_gg = entrate_df.groupby("data").size()
        giorni_anomali = conti_gg[conti_gg > 8]
        if not giorni_anomali.empty:
            anomalie.append({
                "tipo"    : "Giornate con elevata concentrazione di entrate",
                "gravita" : "BASSA",
                "count"   : len(giorni_anomali),
                "totale"  : 0.0,
                "descr"   : (f"{len(giorni_anomali)} giornate con più di 8 movimenti in entrata. "
                             "Verificare che i corrispettivi giornalieri siano stati registrati correttamente."),
                "df"      : giorni_anomali.reset_index().rename(columns={"data":"Data","size":"N. movimenti"}).head(10),
                "giustif" : ("Confrontare il registro corrispettivi telematici o il giornale di fondo cassa "
                             "per le date segnalate con i movimenti bancari della stessa giornata."),
                "norma"   : "Art. 22 D.P.R. 633/1972 — obbligo di registrazione dei corrispettivi",
            })

    # ── 6. Concentrazione: pochi clienti = molti ricavi ─────────────────────
    entrate_pos2 = banca[banca["entrata"] > 0]
    if len(entrate_pos2) >= 5:
        top3_sum = entrate_pos2.nlargest(3, "entrata")["entrata"].sum()
        conc_pct = top3_sum / tot_entrate * 100 if tot_entrate > 0 else 0
        if conc_pct > 60:
            anomalie.append({
                "tipo"    : "Elevata concentrazione delle entrate (top-3 movimenti)",
                "gravita" : "BASSA",
                "count"   : 3,
                "totale"  : top3_sum,
                "descr"   : (f"I 3 movimenti più grandi rappresentano il {conc_pct:.1f}% del totale entrate. "
                             "Alta concentrazione che può attirare attenzione in sede di controllo."),
                "df"      : entrate_pos2.nlargest(3, "entrata"),
                "giustif" : ("Documentare con fatture attive o contratti corrispondenti ai versamenti di importo elevato."),
                "norma"   : "Circ. AdE n. 32/E 2006 — analisi di rischio sui rapporti finanziari",
            })

    # ── Indice di rischio composito ──────────────────────────────────────────
    rischio_pct = min(
        delta_pct
        + sum(20 if a["gravita"] == "ALTA"  else 0 for a in anomalie)
        + sum(10 if a["gravita"] == "MEDIA" else 0 for a in anomalie)
        + sum( 3 if a["gravita"] == "BASSA" else 0 for a in anomalie),
        100
    )

    return {
        "tot_entrate"   : tot_entrate,
        "tot_uscite"    : tot_uscite,
        "tot_ricavi"    : tot_ricavi,
        "tot_iva"       : tot_iva,
        "tot_fatturato" : tot_fatturato,
        "delta"         : delta,
        "delta_pct"     : delta_pct,
        "anomalie"      : anomalie,
        "rischio_pct"   : rischio_pct,
        "n_movimenti"   : len(banca),
        "n_corrispettivi": len(corr),
    }


# ─────────────────────────────────────────────────────────────────────────────
# HELPER DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

def fmt_eur(val: float) -> str:
    return f"€ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def colore_rischio(pct: float) -> tuple:
    if pct >= 30:
        return "#C8102E", "🔴 RISCHIO ELEVATO", "box-alto"
    if pct >= 15:
        return "#E8A020", "🟡 RISCHIO MEDIO", "box-medio"
    return "#1A7F5A", "🟢 RISCHIO BASSO", "box-basso"


def badge_gravita(grav: str) -> str:
    cls = {"ALTA": "badge-alta", "MEDIA": "badge-media", "BASSA": "badge-bassa"}.get(grav, "badge-bassa")
    return f'<span class="{cls}">{grav}</span>'


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🏦 Compliance Bancaria")
    st.markdown("**Strumento professionale** per dottori commercialisti e revisori legali.")
    st.markdown("---")
    st.markdown("### 📋 Riferimenti normativi")
    st.markdown("""
- Art. 32 D.P.R. 600/1973
- Art. 51 D.P.R. 633/1972
- Art. 7 D.P.R. 605/1973
- L. 212/2000 (Statuto contribuente)
- D.Lgs. 218/1997 (Adesione)
- D.Lgs. 471/1997 (Sanzioni)
- D.Lgs. 472/1997, art. 13 (Ravvedimento)
- D.Lgs. 74/2000 (Reati tributari)
- D.Lgs. 87/2024 (Riforma sanzioni)
    """)
    st.markdown("---")
    st.markdown("### ⚖️ Soglie penali D.Lgs. 74/2000")
    st.markdown("""
| Reato | Soglia imposta |
|-------|---------------|
| Dich. infedele (art. 4) | > 150.000 € |
| Omessa dich. (art. 5) | > 50.000 € |
| Fatture false (art. 8) | Sempre |
    """)
    st.markdown("---")
    st.markdown("### 📎 Sanzioni amministrative")
    st.markdown("""
- **Infedele dichiarazione**: 90%–180%
- **Omessa dichiarazione**: 120%–240%
- **Omessa fatturazione**: 90%–180%
- **Ravvedimento operoso**: riduzione fino a 1/9
    """)
    st.markdown("---")
    st.caption("⚠️ Strumento indicativo. Non sostituisce la consulenza professionale.")


# ─────────────────────────────────────────────────────────────────────────────
# HEADER PRINCIPALE
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="app-header">
    <h1>🏦 Compliance Bancaria Analyzer</h1>
    <p>Analisi anomalie estratti conto bancari vs corrispettivi/ricavi dichiarati — Prevenzione lettere Agenzia delle Entrate</p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# UPLOAD FILE
# ─────────────────────────────────────────────────────────────────────────────

tab_upload, tab_formato, tab_guida = st.tabs(["📂 Carica file", "📋 Formato atteso", "📖 Guida normativa"])

with tab_upload:
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 🏛️ Estratto conto bancario")
        st.markdown("""
<div class="box-info">
Carica il file Excel, CSV o <strong>PDF</strong> dell'estratto conto bancario dell'impresa per il periodo contestato.
Sono supportate le esportazioni di tutti i principali istituti di credito italiani.
</div>
""", unsafe_allow_html=True)
        files_banca = st.file_uploader(
            "Trascina o seleziona uno o più file (es. 4 trimestri)",
            type=["xlsx", "xls", "csv", "pdf"],
            key="banca",
            accept_multiple_files=True,
            help="Puoi caricare più file insieme. Supporta .xlsx, .xls, .csv e .pdf. Banca Intesa: usa il PDF dell'estratto."
        )

    with col2:
        st.markdown("#### 📋 Registro corrispettivi / fatture")
        st.markdown("""
<div class="box-info">
Carica il registro corrispettivi telematici, il registro IVA vendite o l'elenco fatture attive in formato Excel, CSV o <strong>PDF</strong>.
Deve contenere almeno la colonna o il campo con l'imponibile/ricavo.
</div>
""", unsafe_allow_html=True)
        files_corr = st.file_uploader(
            "Trascina o seleziona uno o più file (es. 4 trimestri)",
            type=["xlsx", "xls", "csv", "pdf"],
            key="corr",
            accept_multiple_files=True,
            help="Puoi caricare più file insieme. Il sistema rileva automaticamente il formato e concatena i dati."
        )

    st.markdown("---")

    # Parametri analisi
    with st.expander("⚙️ Parametri avanzati (opzionale)"):
        col_p1, col_p2, col_p3 = st.columns(3)
        with col_p1:
            soglia_grande = st.number_input(
                "Soglia prelievi anomali (€)", min_value=500, max_value=50000,
                value=3000, step=500,
                help="Prelievi superiori a questa soglia senza causale identificabile vengono segnalati."
            )
        with col_p2:
            moltiplicatore = st.number_input(
                "Moltiplicatore media versamenti", min_value=1.5, max_value=10.0,
                value=3.0, step=0.5,
                help="Versamenti superiori a N× la media vengono segnalati come anomali."
            )
        with col_p3:
            soglia_tonda = st.number_input(
                "Multiplo cifra tonda (€)", min_value=100, max_value=1000,
                value=500, step=100,
                help="Versamenti esattamente multipli di questo importo vengono segnalati."
            )

    btn_avvia = st.button(
        "🔍 Avvia analisi anomalie",
        type="primary",
        use_container_width=True,
        disabled=(not files_banca or not files_corr)
    )

    if not files_banca or not files_corr:
        st.info("📌 Carica entrambi i file per avviare l'analisi.")


with tab_formato:
    st.markdown("### Formato atteso dei file")
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        st.markdown("#### Estratto conto bancario")
        st.dataframe(pd.DataFrame({
            "Data":        ["01/03/2024", "05/03/2024", "12/03/2024", "18/03/2024"],
            "Descrizione": ["Versamento cliente Rossi", "F24 IVA trimestrale", "Bonifico Bianchi Srl", "Prelievo cassa"],
            "Avere":       [5000.00, "", 8500.00, ""],
            "Dare":        ["", 3200.00, "", 1500.00],
        }), use_container_width=True)
        st.caption("💡 Accettate anche: colonne 'Entrate/Uscite', 'Accredito/Addebito', 'Credit/Debit', oppure colonna unica 'Importo' con segno.")

    with col_f2:
        st.markdown("#### Registro corrispettivi / fatture attive")
        st.dataframe(pd.DataFrame({
            "Data":         ["01/03/2024", "05/03/2024", "12/03/2024", "18/03/2024"],
            "Descrizione":  ["Vendita prodotti", "Prestazione servizi", "Corrispettivi giorn.", "Fattura n. 42"],
            "Imponibile":   [4098.36, 6967.21, 6557.38, 2459.02],
            "IVA":          [901.64, 1532.79, 1442.62, 540.98],
        }), use_container_width=True)
        st.caption("💡 Accettate anche: colonne 'Ricavo', 'Totale', 'Fatturato', 'Corrispettivo', 'Amount'. La colonna IVA è opzionale.")

    st.markdown("---")
    st.markdown("""
<div class="box-warning">
⚠️ <strong>Suggerimento Excel/CSV:</strong> Se il file non viene letto correttamente, rinominare le colonne chiave 
come mostrato nella tabella sopra. I nomi vengono riconosciuti sia in italiano che in inglese.
Assicurarsi che gli importi siano numerici (senza simboli di valuta nelle celle).
</div>
<div class="box-warning" style="border-color:#2E5FA3; background:#EBF0F8;">
📄 <strong>Suggerimento PDF:</strong> Il sistema estrae automaticamente testo e importi dai PDF digitali 
(non da PDF scansionati/immagine). Supporta i formati di: Intesa Sanpaolo, UniCredit, BancoBPM, 
Fineco, BPER, MPS, Banco BPM, Crédit Agricole, ING, N26, Revolut. 
Se il PDF non viene riconosciuto, esportare il file in formato Excel direttamente dall'home banking.
</div>
""", unsafe_allow_html=True)


with tab_guida:
    st.markdown("### 📖 Guida alla difesa del contribuente")

    with st.expander("1️⃣ La lettera di compliance — cosa è e cosa fare"):
        st.markdown("""
La **lettera di compliance** è un invito alla collaborazione dell'Agenzia delle Entrate, **non un avviso di accertamento**.
Non ha effetti esecutivi, ma la mancata risposta può portare all'apertura di un procedimento formale.

**Cosa fare entro 30 giorni:**
- Raccogliere tutti gli estratti conto del periodo contestato
- Effettuare la riconciliazione bancaria analitica
- Predisporre la documentazione giustificativa
- Rispondere formalmente con lettera professionale su carta intestata dello Studio

**Base normativa:** Art. 36-ter D.P.R. 600/1973 — D.Lgs. 128/2015 — Circ. AdE n. 6/E 2023
        """)

    with st.expander("2️⃣ Le presunzioni bancarie — come funzionano"):
        st.markdown("""
L'art. 32, co. 1, n. 2 D.P.R. 600/1973 prevede che:

- **Versamenti non giustificati** → si presumono **ricavi** per le **imprese**
- **Prelievi non giustificati** → si presumono **acquisti in nero** che hanno generato ricavi in nero (solo per imprese — non per professionisti dopo Corte Cost. 228/2014)

L'onere della prova contraria è **a carico del contribuente**.

**Giurisprudenza chiave:**
- Corte Cost. n. 228/2014 — presunzione prelievi illegittima per lavoratori autonomi
- Cass. SS.UU. n. 26635/2009 — onere della prova nelle indagini finanziarie
- Cass. n. 20668/2017 — presunzioni bancarie per le imprese
        """)

    with st.expander("3️⃣ Il ravvedimento operoso — quando conviene"):
        st.markdown("""
Se residua un'anomalia non completamente giustificabile, il **ravvedimento operoso** (art. 13 D.Lgs. 472/1997) 
consente di regolarizzare versando:

| Tempistica | Riduzione sanzione |
|------------|-------------------|
| Entro 30 gg dalla violazione | 1/10 del minimo |
| Entro 90 gg | 1/9 del minimo |
| Entro 1 anno | 1/8 del minimo |
| Entro 2 anni | 1/7 del minimo |
| Oltre 2 anni | 1/6 del minimo |
| Dopo PVC ma prima dell'accertamento | 1/5 del minimo |

Il ravvedimento è **ancora possibile** fino alla notifica dell'avviso di accertamento.
        """)

    with st.expander("4️⃣ Possibili giustificazioni dei movimenti bancari"):
        st.markdown("""
**Per i versamenti (accrediti):**
- Finanziamenti soci con verbale assembleare e data certa
- Mutui e aperture di credito bancarie
- Girofondi tra conti propri dell'impresa o del titolare
- Rimborsi spese anticipate per conto terzi
- Premi assicurativi e indennizzi
- Contributi pubblici, fondi europei, contributi a fondo perduto
- Cessione di beni strumentali (plusvalenze già contabilizzate)
- Recupero crediti pregressi di anni precedenti già dichiarati
- Anticipi da clienti già inclusi nei corrispettivi IVA

**Per i prelievi (addebiti):**
- Pagamenti fornitori documentati da fatture passive
- Prelevamenti per cassa aziendale (registro cassa aggiornato)
- Pagamento stipendi, compensi, collaboratori
- Versamento imposte, contributi INPS/INAIL, F24
- Restituzione di prestiti ricevuti
- Spese personali del titolare (impresa individuale)
        """)


# ─────────────────────────────────────────────────────────────────────────────
# ANALISI E RISULTATI
# ─────────────────────────────────────────────────────────────────────────────

if btn_avvia and files_banca and files_corr:

    with st.spinner("⏳ Lettura e riconciliazione di tutti i file in corso..."):

        # ── Leggi tutti i file banca (supporta multi-file) ────────────────────
        df_banca_parts = []
        for f in files_banca:
            raw = f.read()
            fname = f.name.lower()
            if fname.endswith(".pdf"):
                if not PDF_AVAILABLE:
                    st.error("❌ pdfplumber non installato. Aggiungilo a requirements.txt")
                    st.stop()
                part = parse_banca_intesa_pdf(raw)
            else:
                part = carica_estratto_conto(io.BytesIO(raw))
            if part is not None and not part.empty:
                df_banca_parts.append(part)
                st.caption(f"  ✓ Banca: **{f.name}** — {len(part)} movimenti")

        # ── Leggi tutti i file corrispettivi (supporta multi-file) ────────────
        df_corr_parts = []
        for f in files_corr:
            raw = f.read()
            fname = f.name.lower()
            if fname.endswith(".pdf"):
                if not PDF_AVAILABLE:
                    st.error("❌ pdfplumber non installato. Aggiungilo a requirements.txt")
                    st.stop()
                part = parse_corrispettivi_pdf(raw)
            else:
                part = carica_corrispettivi(io.BytesIO(raw))
            if part is not None and not part.empty:
                df_corr_parts.append(part)
                st.caption(f"  ✓ Corrispettivi: **{f.name}** — {len(part)} righe")

        df_banca = pd.concat(df_banca_parts, ignore_index=True) if df_banca_parts else None
        df_corr  = pd.concat(df_corr_parts,  ignore_index=True) if df_corr_parts  else None

        # ── Avviso per Banca Intesa Q1-Q3 (font non estraibile) ───────────────
        if df_banca is not None and "_importo_leggibile" in df_banca.columns:
            n_miss = (df_banca["_importo_leggibile"] == False).sum()
            if n_miss > 0:
                st.warning(
                    f"⚠️ **{n_miss} transazioni senza importo** (Banca Intesa Q1-Q3): "
                    "il PDF usa un font proprietario per gli importi di quei trimestri. "
                    "Per avere i dati completi scarica l'estratto Q1-Q3 in formato Excel dall'home banking."
                )
            df_banca = df_banca[df_banca["_importo_leggibile"] == True].drop(
                columns=["_importo_leggibile"], errors="ignore"
            )

    if df_banca is None or df_banca.empty:
        st.error("❌ Nessun movimento bancario letto. Verifica i file caricati.")
        st.stop()

    if df_corr is None or df_corr.empty:
        st.error("❌ Nessuna riga corrispettivi letta. Verifica i file caricati.")
        st.stop()

    # Override parametri con quelli avanzati
    res = analizza(df_banca, df_corr)

    st.success(f"✅ Analisi completata — {res['n_movimenti']} movimenti bancari e {res['n_corrispettivi']} righe corrispettivi elaborati.")
    st.markdown("---")

    # ── KPI ────────────────────────────────────────────────────────────────
    st.markdown("### 📊 Riepilogo metriche principali")
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("Totale entrate bancarie", fmt_eur(res["tot_entrate"]),
                  help="Somma di tutti gli accrediti sul conto corrente nel periodo analizzato.")
    with k2:
        st.metric("Fatturato dichiarato (IVA incl.)", fmt_eur(res["tot_fatturato"]),
                  help=f"Imponibile {fmt_eur(res['tot_ricavi'])} + IVA {fmt_eur(res['tot_iva'])}")
    with k3:
        delta_sign = "+" if res["delta"] > 0 else ""
        st.metric("Delta anomalo", fmt_eur(abs(res["delta"])),
                  delta=f"{delta_sign}{res['delta']:,.2f}€ ({res['delta_pct']:.1f}%)",
                  delta_color="inverse" if res["delta"] > 0 else "normal",
                  help="Differenza assoluta tra entrate bancarie e fatturato dichiarato.")
    with k4:
        n_alte = sum(1 for a in res["anomalie"] if a["gravita"] == "ALTA")
        st.metric("Anomalie rilevate", len(res["anomalie"]),
                  delta=f"{n_alte} ad alta gravità" if n_alte else "Nessuna ad alta gravità",
                  delta_color="inverse" if n_alte > 0 else "off")

    st.markdown("---")

    # ── RISCHIO ────────────────────────────────────────────────────────────
    col_rischio, col_riepilogo = st.columns([1, 1])

    with col_rischio:
        st.markdown("### 🎯 Indicatore di rischio compliance")
        pct = res["rischio_pct"]
        col_r, label_r, box_r = colore_rischio(pct)

        # Progress bar colorata
        st.progress(min(pct / 100, 1.0))
        st.markdown(f"""
<div class="{box_r}">
<span style="font-size:32px; font-weight:900; color:{col_r};">{pct:.0f}%</span>
&nbsp;&nbsp;
<span style="font-size:16px; font-weight:800; color:{col_r};">{label_r}</span>
<br><small style="color:#555;">
{"Alta probabilità di ricezione lettera di compliance. Avviare immediatamente la riconciliazione e valutare il ravvedimento operoso." if pct >= 30
 else "Rischio moderato. Documentare le anomalie rilevate con probatorio scritto." if pct >= 15
 else "Situazione sostanzialmente regolare. Mantenere documentazione aggiornata."}
</small>
</div>
""", unsafe_allow_html=True)

    with col_riepilogo:
        st.markdown("### 📋 Tabella di riconciliazione")
        riepilogo_df = pd.DataFrame({
            "Voce": [
                "Totale entrate bancarie",
                "— di cui: fatturato IVA inclusa",
                "— di cui: delta non giustificato",
                "Imponibile dichiarato",
                "IVA su ricavi dichiarati",
                "Delta %",
            ],
            "Importo": [
                fmt_eur(res["tot_entrate"]),
                fmt_eur(res["tot_fatturato"]),
                fmt_eur(abs(res["delta"])),
                fmt_eur(res["tot_ricavi"]),
                fmt_eur(res["tot_iva"]),
                f"{res['delta_pct']:.2f}%",
            ]
        })
        st.dataframe(riepilogo_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── ANOMALIE ───────────────────────────────────────────────────────────
    st.markdown("### ⚠️ Anomalie rilevate")

    if not res["anomalie"]:
        st.success("✅ Nessuna anomalia significativa rilevata. La situazione appare regolare.")
    else:
        for i, a in enumerate(res["anomalie"]):
            col_a, box_a = (
                ("#C8102E", "box-alto") if a["gravita"] == "ALTA" else
                ("#E8A020", "box-medio") if a["gravita"] == "MEDIA" else
                ("#1A7F5A", "box-basso")
            )
            titolo = f"{badge_gravita(a['gravita'])} &nbsp; {a['tipo']}"
            if a["totale"] > 0:
                titolo += f" &nbsp;|&nbsp; <strong>{fmt_eur(a['totale'])}</strong>"

            with st.expander(f"{'🔴' if a['gravita']=='ALTA' else '🟡' if a['gravita']=='MEDIA' else '🟢'} [{a['gravita']}] {a['tipo']}" + (f" — {fmt_eur(a['totale'])}" if a["totale"] > 0 else "")):
                st.markdown(f"""
<div class="{box_a}">
{titolo}
<br><br>
<strong>Descrizione:</strong> {a['descr']}
<br><br>
<strong>Base normativa:</strong> <em>{a['norma']}</em>
</div>
""", unsafe_allow_html=True)

                st.markdown("**💡 Possibili giustificazioni documentali:**")
                st.info(a["giustif"])

                if isinstance(a["df"], pd.DataFrame) and not a["df"].empty:
                    st.markdown("**Dettaglio movimenti:**")
                    st.dataframe(a["df"][["data", "descrizione", "entrata", "uscita"] if "entrata" in a["df"].columns else a["df"].columns.tolist()],
                                 use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── AZIONI RACCOMANDATE ────────────────────────────────────────────────
    st.markdown("### 📌 Azioni raccomandate")

    pct = res["rischio_pct"]
    if pct >= 30:
        st.markdown("""
<div class="box-alto">
<strong>⚠️ RISCHIO ELEVATO — Azioni urgenti:</strong>
<ul>
<li>Avviare immediatamente la <strong>riconciliazione analitica</strong> operazione per operazione con il libro mastro</li>
<li>Raccogliere contratti di finanziamento soci con data certa, verbali assembleari, estratti conto altri conti</li>
<li>Valutare il <strong>ravvedimento operoso</strong> per anomalie non giustificabili (art. 13 D.Lgs. 472/1997)</li>
<li>Predisporre la risposta formale alla lettera di compliance con allegata documentazione probatoria</li>
<li>Verificare se il delta supera le <strong>soglie di rilevanza penale</strong> (D.Lgs. 74/2000 artt. 4 e 5)</li>
<li>Considerare l'istanza di contraddittorio preventivo ai sensi dell'art. 12 co. 7 L. 212/2000</li>
</ul>
</div>
""", unsafe_allow_html=True)
    elif pct >= 15:
        st.markdown("""
<div class="box-medio">
<strong>⚡ RISCHIO MEDIO — Azioni preventive:</strong>
<ul>
<li>Documentare le anomalie rilevate con probatorio scritto da conservare nel fascicolo</li>
<li>Verificare la corretta registrazione di tutti i corrispettivi telematici e fatture attive</li>
<li>Aggiornare e quadrare il registro di cassa con i prelievi del periodo</li>
<li>Conservare tutta la documentazione fiscale per almeno 10 anni</li>
<li>Monitorare eventuali comunicazioni successive dell'Agenzia delle Entrate</li>
</ul>
</div>
""", unsafe_allow_html=True)
    else:
        st.markdown("""
<div class="box-basso">
<strong>✅ RISCHIO BASSO — Mantenimento della compliance:</strong>
<ul>
<li>Situazione sostanzialmente regolare — continuare a mantenere la documentazione aggiornata</li>
<li>Riconciliare mensilmente il conto bancario con i registri IVA e il libro mastro</li>
<li>Documentare preventivamente le eventuali anomalie residue</li>
<li>Verificare la corretta emissione e registrazione di tutti i corrispettivi</li>
</ul>
</div>
""", unsafe_allow_html=True)

    # ── EXPORT ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 💾 Esporta risultati")
    col_e1, col_e2 = st.columns(2)

    with col_e1:
        # Export Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            # Sheet 1: Riepilogo
            pd.DataFrame({
                "Voce": ["Totale entrate bancarie", "Totale uscite bancarie",
                         "Imponibile dichiarato", "IVA dichiarata", "Totale fatturato",
                         "Delta (entrate-fatturato)", "Delta %", "Indice di rischio %"],
                "Valore": [res["tot_entrate"], res["tot_uscite"],
                           res["tot_ricavi"], res["tot_iva"], res["tot_fatturato"],
                           res["delta"], f"{res['delta_pct']:.2f}%", f"{res['rischio_pct']:.0f}%"],
            }).to_excel(writer, sheet_name="Riepilogo", index=False)

            # Sheet 2: Anomalie
            if res["anomalie"]:
                pd.DataFrame([{
                    "Tipo anomalia": a["tipo"],
                    "Gravità": a["gravita"],
                    "N. movimenti": a["count"],
                    "Importo totale €": a["totale"],
                    "Descrizione": a["descr"],
                    "Possibili giustificazioni": a["giustif"],
                    "Norma": a["norma"],
                } for a in res["anomalie"]]).to_excel(writer, sheet_name="Anomalie", index=False)

            # Sheet 3: Estratto conto
            df_banca.to_excel(writer, sheet_name="Estratto conto", index=False)

            # Sheet 4: Corrispettivi
            df_corr.to_excel(writer, sheet_name="Corrispettivi", index=False)

        st.download_button(
            "📥 Scarica report Excel",
            data=output.getvalue(),
            file_name=f"compliance_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    with col_e2:
        # Export CSV riconciliazione
        riepilogo_csv = pd.DataFrame({
            "Voce": ["Totale entrate bancarie", "Totale fatturato IVA incl.", "Delta",
                     "Delta %", "N. anomalie", "Indice rischio %"],
            "Valore": [res["tot_entrate"], res["tot_fatturato"], res["delta"],
                       f"{res['delta_pct']:.2f}", len(res["anomalie"]), f"{res['rischio_pct']:.0f}"],
        })
        st.download_button(
            "📥 Scarica riepilogo CSV",
            data=riepilogo_csv.to_csv(index=False, sep=";").encode("utf-8-sig"),
            file_name=f"compliance_riepilogo_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.markdown("""
<div class="box-info" style="margin-top:20px;">
⚖️ <em><strong>Nota legale:</strong> Questo strumento ha finalità indicativa e non sostituisce la consulenza 
professionale di un dottore commercialista. I risultati devono essere verificati caso per caso alla luce 
della documentazione contabile completa. Tutti i riferimenti normativi e giurisprudenziali devono essere 
verificati in relazione al periodo d'imposta e alla fattispecie concreta.</em>
</div>
""", unsafe_allow_html=True)
