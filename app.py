#!/usr/bin/env python3
"""
Convertitore batch di file EML in PDF con estrazione allegati.
Carica file .eml, genera PDF con report e restituisce archivio ZIP.
"""

import os
import sys
import uuid
import shutil
import tempfile
import zipfile
import html as html_mod
import email.utils
from pathlib import Path
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage

from flask import Flask, request, jsonify, send_file, abort
from bs4 import BeautifulSoup
from fpdf import FPDF

# ── Configurazione ──────────────────────────────────────────────────────────

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB max upload

TEMP_ROOT = Path(tempfile.gettempdir()) / "eml_converter"
TEMP_ROOT.mkdir(exist_ok=True)

# Trova un font TTF Unicode sul sistema
_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
]

FONT_REGULAR = None
for fp in _FONT_PATHS:
    if os.path.isfile(fp):
        FONT_REGULAR = fp
        break

if FONT_REGULAR is None:
    raise RuntimeError(
        "Nessun font TTF trovato. Cerca Arial o DejaVuSans nei percorsi di sistema."
    )


# ── Helpers EML ─────────────────────────────────────────────────────────────

def decode_header_value(value):
    """Decodifica un header email potenzialmente codificato (RFC 2047)."""
    if value is None:
        return ""
    parts = email.header.decode_header(value)
    result = []
    for text, charset in parts:
        if isinstance(text, bytes):
            try:
                result.append(text.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                result.append(text.decode("utf-8", errors="replace"))
        else:
            result.append(str(text))
    return " ".join(result)


def extract_body(msg):
    """
    Estrae il corpo testuale del messaggio.
    Preferisce text/plain; se assente, estrae testo da text/html.
    """
    if msg.is_multipart():
        # Prima cerca text/plain
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        return payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        return payload.decode("utf-8", errors="replace")
        # Poi cerca text/html
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/html" and "attachment" not in disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        html_str = payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        html_str = payload.decode("utf-8", errors="replace")
                    soup = BeautifulSoup(html_str, "html.parser")
                    return soup.get_text(separator="\n", strip=True)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            if msg.get_content_type() == "text/html":
                try:
                    html_str = payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    html_str = payload.decode("utf-8", errors="replace")
                soup = BeautifulSoup(html_str, "html.parser")
                return soup.get_text(separator="\n", strip=True)
            else:
                try:
                    return payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    return payload.decode("utf-8", errors="replace")
    return ""


def extract_attachments(msg):
    """Estrae gli allegati dal messaggio. Restituisce lista di dict."""
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition or (
                part.get_content_maintype() not in ("text", "multipart")
                and part.get_filename()
            ):
                filename = part.get_filename()
                if filename:
                    filename = decode_header_value(filename)
                    payload = part.get_payload(decode=True)
                    attachments.append(
                        {
                            "filename": filename,
                            "content_type": part.get_content_type(),
                            "size": len(payload) if payload else 0,
                        }
                    )
    return attachments


def format_size(size_bytes):
    """Formatta la dimensione in byte in formato leggibile."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ── Generazione PDF ─────────────────────────────────────────────────────────

class EMLtoPDF(FPDF):
    """Generatore PDF specializzato per report email."""

    def __init__(self):
        super().__init__("P", "mm", "A4")
        self.add_font("UFont", "", FONT_REGULAR)
        self.set_auto_page_break(True, 20)
        # Colori tema
        self.colors = {
            "primary": (26, 58, 92),       # blu inchiostro #1A3A5C
            "accent": (203, 58, 42),        # vermiglio #CB3A2A
            "text": (26, 29, 33),           # #1A1D21
            "text_secondary": (93, 109, 126),  # #5D6D7E
            "border": (216, 211, 203),      # #D8D3CB
            "surface": (245, 244, 241),     # #F5F4F1
            "white": (255, 255, 255),
        }

    def _rgb(self, name):
        return self.colors[name]

    def header_block(self, subject, sender, recipient, date_str):
        """Blocco intestazione del report."""
        r, g, b = self._rgb("primary")
        self.set_fill_color(r, g, b)
        self.rect(15, 15, 180, 28, "F")

        self.set_y(19)
        self.set_font("UFont", "", 7)
        self.set_text_color(*self._rgb("white"))
        self.set_x(18)
        self.cell(174, 4, "RAPPORTO EMAIL", align="L")

        self.set_y(24)
        self.set_font("UFont", "", 13)
        self.set_x(18)
        # Tronca soggetto lungo
        display_subject = subject if len(subject) < 85 else subject[:82] + "..."
        self.cell(174, 8, display_subject or "(nessun oggetto)", align="L")

        # Metadata
        self.set_y(50)
        self.set_font("UFont", "", 8)
        meta_items = [
            ("MITTENTE", sender or "—"),
            ("DESTINATARIO", recipient or "—"),
            ("DATA", date_str or "—"),
        ]
        col_w = 58
        x_positions = [18, 18 + col_w, 18 + 2 * col_w]
        for i, (label, value) in enumerate(meta_items):
            x = x_positions[i]
            self.set_xy(x, 50)
            self.set_text_color(*self._rgb("text_secondary"))
            self.cell(col_w, 4, label, align="L")
            self.set_xy(x, 55)
            self.set_text_color(*self._rgb("text"))
            # Tronca se troppo lungo
            display_val = value if len(value) < 40 else value[:37] + "..."
            self.cell(col_w, 4, display_val, align="L")

        # Linea separatrice
        self.set_y(62)
        r2, g2, b2 = self._rgb("border")
        self.set_draw_color(r2, g2, b2)
        self.line(18, 62, 192, 62)

    def body_section(self, body_text):
        """Sezione corpo del messaggio."""
        self.set_y(67)
        self.set_font("UFont", "", 8)
        self.set_text_color(*self._rgb("text_secondary"))
        self.set_x(18)
        self.cell(174, 4, "CORPO DEL MESSAGGIO", align="L")

        self.set_y(74)
        self.set_text_color(*self._rgb("text"))
        self.set_font("UFont", "", 9)

        # Rendi il testo sicuro sostituendo caratteri problematici
        # ma preservando unicode
        safe_body = body_text.replace("\r\n", "\n").replace("\r", "\n")

        # Stampa il corpo riga per riga, con word wrap
        line_height = 4.5
        max_width = 174
        for line in safe_body.split("\n"):
            if self.get_y() > 270:  # vicino al fondo pagina
                self.add_page()
            if not line.strip():
                self.set_x(18)
                self.cell(max_width, line_height, "", align="L")
                self.ln(line_height)
                continue
            # Gestisci linee molto lunghe
            self.set_x(18)
            self.multi_cell(max_width, line_height, line, align="L")

    def attachments_section(self, attachments):
        """Sezione elenco allegati."""
        current_y = self.get_y() + 4
        if current_y > 250:
            self.add_page()
            current_y = self.get_y()

        self.set_y(current_y)
        self.set_draw_color(*self._rgb("border"))
        self.line(18, self.get_y(), 192, self.get_y())
        self.ln(5)

        self.set_font("UFont", "", 8)
        self.set_text_color(*self._rgb("text_secondary"))
        self.set_x(18)
        count = len(attachments)
        label = f"ALLEGATI ({count})" if count else "NESSUN ALLEGATO"
        self.cell(174, 4, label, align="L")
        self.ln(7)

        if attachments:
            # Tabella allegati
            self.set_font("UFont", "", 8)
            # Header tabella
            self.set_fill_color(*self._rgb("surface"))
            self.set_text_color(*self._rgb("text_secondary"))
            self.set_x(18)
            self.cell(6, 5, "#", align="C", fill=True)
            self.set_x(24)
            self.cell(110, 5, "Nome file", align="L", fill=True)
            self.set_x(134)
            self.cell(30, 5, "Tipo", align="L", fill=True)
            self.set_x(164)
            self.cell(26, 5, "Dimensione", align="R", fill=True)
            self.ln(7)

            # Righe
            self.set_text_color(*self._rgb("text"))
            for i, att in enumerate(attachments, 1):
                if self.get_y() > 270:
                    self.add_page()
                self.set_x(18)
                self.cell(6, 5, str(i), align="C")
                self.set_x(24)
                disp_name = att["filename"] if len(att["filename"]) < 50 else att["filename"][:47] + "..."
                self.cell(110, 5, disp_name, align="L")
                self.set_x(134)
                ctype = att["content_type"]
                disp_type = ctype if len(ctype) < 18 else ctype[:15] + "..."
                self.cell(30, 5, disp_type, align="L")
                self.set_x(164)
                self.cell(26, 5, format_size(att["size"]), align="R")
                self.ln(5.5)

    def footer(self):
        """Piè di pagina."""
        self.set_y(-15)
        self.set_font("UFont", "", 6)
        self.set_text_color(*self._rgb("text_secondary"))
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        self.cell(0, 4, f"Generato il {now} — Convertitore EML→PDF", align="C")


def generate_pdf(file_data, original_filename):
    """
    Genera un PDF da un file EML (bytes).
    Restituisce il percorso del file PDF creato.
    """
    # Parsing EML
    msg = BytesParser(policy=policy.default).parsebytes(file_data)

    # Estrai header
    subject = decode_header_value(msg.get("Subject", ""))
    sender = decode_header_value(msg.get("From", ""))
    recipient = decode_header_value(msg.get("To", ""))
    date_str = decode_header_value(msg.get("Date", ""))

    # Estrai corpo
    body = extract_body(msg)

    # Estrai allegati
    attachments = extract_attachments(msg)

    # Genera PDF
    pdf = EMLtoPDF()
    pdf.add_page()
    pdf.header_block(subject, sender, recipient, date_str)
    pdf.body_section(body)
    pdf.attachments_section(attachments)

    # Salva PDF
    safe_name = "".join(c for c in original_filename if c.isalnum() or c in "._- ")
    safe_name = safe_name.strip() or "email"
    pdf_name = f"{Path(safe_name).stem}.pdf"
    pdf_path = TEMP_ROOT / pdf_name
    pdf.output(str(pdf_path))

    return pdf_path, {
        "subject": subject,
        "sender": sender,
        "recipient": recipient,
        "date": date_str,
        "body_length": len(body),
        "attachments_count": len(attachments),
        "attachments": attachments,
    }


# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve la pagina frontend."""
    return app.send_static_file("index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    """Riceve file EML, genera PDF e ZIP."""
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "Nessun file caricato."}), 400

    # Crea directory di sessione
    session_id = uuid.uuid4().hex
    session_dir = TEMP_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    results = []
    errors = []

    for f in files:
        if not f.filename:
            continue

        original_name = f.filename
        file_data = f.read()

        # Verifica estensione
        if not original_name.lower().endswith(".eml"):
            errors.append(f"{original_name}: formato non supportato (solo .eml)")
            continue

        try:
            pdf_path, info = generate_pdf(file_data, original_name)
            results.append(
                {
                    "original_name": original_name,
                    "pdf_path": str(pdf_path),
                    "info": info,
                }
            )
        except Exception as e:
            errors.append(f"{original_name}: errore di elaborazione — {str(e)}")

    if not results and errors:
        shutil.rmtree(session_dir, ignore_errors=True)
        return jsonify({"error": "Nessun file elaborato.", "details": errors}), 422

    # Sposta i PDF nella directory di sessione
    for r in results:
        new_path = session_dir / Path(r["pdf_path"]).name
        shutil.move(r["pdf_path"], new_path)
        r["pdf_path"] = str(new_path)

    # Crea ZIP
    zip_name = "eml_to_pdf.zip"
    zip_path = session_dir / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in results:
            pdf_file = Path(r["pdf_path"])
            zf.write(pdf_file, pdf_file.name)

    # Crea file info per cleanup
    info_file = session_dir / "_session_info.txt"
    info_file.write_text(session_id)

    response_data = {
        "session_id": session_id,
        "zip_name": zip_name,
        "total": len(files),
        "processed": len(results),
        "errors": errors,
        "files": [
            {
                "original_name": r["original_name"],
                "subject": r["info"]["subject"],
                "attachments_count": r["info"]["attachments_count"],
            }
            for r in results
        ],
    }

    return jsonify(response_data), 200


@app.route("/api/download/<session_id>", methods=["GET"])
def download_zip(session_id):
    """Serve il file ZIP e pulisce i file temporanei dopo l'invio."""
    # Sicurezza: sanitizza session_id
    if not session_id or not session_id.isalnum():
        abort(400, description="ID sessione non valido")

    session_dir = TEMP_ROOT / session_id
    if not session_dir.exists():
        abort(404, description="Sessione non trovata o scaduta.")

    zip_path = session_dir / "eml_to_pdf.zip"
    if not zip_path.exists():
        abort(404, description="Archivio ZIP non trovato.")

    # Funzione di cleanup dopo il download
    def cleanup_session():
        try:
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
        except Exception:
            pass

    # Usa un generatore per pulire dopo il download
    import threading

    def delayed_cleanup():
        import time

        time.sleep(2)  # Aspetta che il file sia stato inviato
        cleanup_session()

    # Avvia cleanup in background
    t = threading.Thread(target=delayed_cleanup, daemon=True)
    t.start()

    return send_file(
        zip_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name="eml_to_pdf.zip",
    )


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


# ── Pulizia sessioni vecchie all'avvio ──────────────────────────────────────

def cleanup_old_sessions():
    """Rimuove sessioni più vecchie di 1 ora all'avvio."""
    try:
        now = datetime.now().timestamp()
        for item in TEMP_ROOT.iterdir():
            if item.is_dir() and len(item.name) == 32 and item.name.isalnum():
                age = now - item.stat().st_mtime
                if age > 3600:  # 1 ora
                    shutil.rmtree(item, ignore_errors=True)
    except Exception:
        pass


# ── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cleanup_old_sessions()
    port = int(os.environ.get("PORT", 4599))
    print(f"🚀 Avvio server su http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
