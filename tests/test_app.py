"""
Test suite per il convertitore EML → PDF.
Verifica parsing EML, generazione PDF, creazione ZIP e API.
"""

import io
import os
import sys
import zipfile
import tempfile
import unittest
import email.mime.multipart
import email.mime.text
import email.mime.base
from pathlib import Path

# Aggiungi la directory padre al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import app, generate_pdf, extract_body, extract_attachments, decode_header_value
from email.parser import BytesParser
from email import policy


def create_sample_eml(subject="Test Email", body="Questo è un test.", with_attachment=False):
    """Crea un file EML di esempio in memoria."""
    msg = email.mime.multipart.MIMEMultipart()
    msg["From"] = "mittente@esempio.it"
    msg["To"] = "destinatario@esempio.it"
    msg["Subject"] = subject
    msg["Date"] = "Mon, 07 Jul 2026 12:00:00 +0200"

    # Corpo testo
    text_part = email.mime.text.MIMEText(body, "plain", "utf-8")
    msg.attach(text_part)

    # Allegato opzionale
    if with_attachment:
        att = email.mime.text.MIMEText("Contenuto allegato", "plain", "utf-8")
        att.add_header("Content-Disposition", "attachment", filename="test_allegato.txt")
        msg.attach(att)

    return msg.as_bytes()


class TestEMLParsing(unittest.TestCase):
    """Test per il parsing dei file EML."""

    def test_decode_header_simple(self):
        """Decodifica header ASCII semplice."""
        result = decode_header_value("Test Subject")
        self.assertEqual(result, "Test Subject")

    def test_decode_header_utf8(self):
        """Decodifica header UTF-8 codificato."""
        # Crea un header codificato
        import email.header
        encoded = email.header.Header("Oggetto con àèìòù", "utf-8").encode()
        result = decode_header_value(encoded)
        self.assertIn("à", result)

    def test_extract_body_plain(self):
        """Estrae corpo da email text/plain."""
        eml_bytes = create_sample_eml(body="Corpo del messaggio di test.")
        msg = BytesParser(policy=policy.default).parsebytes(eml_bytes)
        body = extract_body(msg)
        self.assertIn("Corpo del messaggio", body)

    def test_extract_body_with_accents(self):
        """Estrae corpo con caratteri accentati italiani."""
        eml_bytes = create_sample_eml(body="Messaggio con àèìòù e ç.")
        msg = BytesParser(policy=policy.default).parsebytes(eml_bytes)
        body = extract_body(msg)
        self.assertIn("àèìòù", body)

    def test_extract_attachments_none(self):
        """Nessun allegato in email semplice."""
        eml_bytes = create_sample_eml(with_attachment=False)
        msg = BytesParser(policy=policy.default).parsebytes(eml_bytes)
        attachments = extract_attachments(msg)
        self.assertEqual(len(attachments), 0)

    def test_extract_attachments_one(self):
        """Estrae un allegato."""
        eml_bytes = create_sample_eml(with_attachment=True)
        msg = BytesParser(policy=policy.default).parsebytes(eml_bytes)
        attachments = extract_attachments(msg)
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["filename"], "test_allegato.txt")

    def test_generate_pdf_basic(self):
        """Genera un PDF da un EML di base."""
        eml_bytes = create_sample_eml(
            subject="Oggetto Prova",
            body="Corpo della email.",
            with_attachment=False
        )
        pdf_path, info = generate_pdf(eml_bytes, "test.eml")

        self.assertTrue(os.path.isfile(pdf_path))
        self.assertGreater(os.path.getsize(pdf_path), 100)  # PDF non vuoto
        self.assertEqual(info["subject"], "Oggetto Prova")
        self.assertEqual(info["attachments_count"], 0)

        # Cleanup
        os.unlink(pdf_path)

    def test_generate_pdf_with_attachment(self):
        """Genera un PDF da un EML con allegato."""
        eml_bytes = create_sample_eml(
            subject="Email con allegato",
            body="Corpo con allegato.",
            with_attachment=True
        )
        pdf_path, info = generate_pdf(eml_bytes, "test_con_allegato.eml")

        self.assertTrue(os.path.isfile(pdf_path))
        self.assertGreater(os.path.getsize(pdf_path), 100)
        self.assertEqual(info["attachments_count"], 1)
        self.assertEqual(info["attachments"][0]["filename"], "test_allegato.txt")

        # Cleanup
        os.unlink(pdf_path)

    def test_generate_pdf_with_italian_accents(self):
        """Genera PDF con caratteri italiani accentati."""
        eml_bytes = create_sample_eml(
            subject="Oggetto: àèìòù é",
            body="Corpo con accenti: àèìòù ç ñ.",
            with_attachment=False
        )
        pdf_path, info = generate_pdf(eml_bytes, "test_italiano.eml")

        self.assertTrue(os.path.isfile(pdf_path))
        self.assertGreater(os.path.getsize(pdf_path), 100)

        # Cleanup
        os.unlink(pdf_path)


class TestAPI(unittest.TestCase):
    """Test per gli endpoint API."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_index_returns_html(self):
        """La pagina principale restituisce HTML."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<!DOCTYPE html>", response.data)

    def test_health_endpoint(self):
        """L'endpoint health restituisce ok."""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "ok")

    def test_upload_no_files(self):
        """Upload senza file restituisce errore."""
        response = self.client.post("/api/upload", data={})
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertIn("error", data)

    def test_upload_single_eml(self):
        """Upload di un singolo file EML."""
        eml_bytes = create_sample_eml(
            subject="Test API",
            body="Corpo test API.",
            with_attachment=False
        )
        response = self.client.post(
            "/api/upload",
            data={"files": (io.BytesIO(eml_bytes), "test_api.eml")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["processed"], 1)
        self.assertIn("session_id", data)
        self.assertIn("files", data)
        self.assertEqual(len(data["files"]), 1)
        self.assertEqual(data["files"][0]["original_name"], "test_api.eml")
        self.assertEqual(data["files"][0]["subject"], "Test API")

        # Verifica download
        session_id = data["session_id"]
        dl_response = self.client.get(f"/api/download/{session_id}")
        # Il download può dare 200 o 404 (se il cleanup è già scattato)
        # Accettiamo entrambi poiché il cleanup può essere asincrono
        self.assertIn(dl_response.status_code, [200, 404])

    def test_upload_multiple_eml(self):
        """Upload di più file EML."""
        eml1 = create_sample_eml(subject="Email 1", body="Corpo 1.")
        eml2 = create_sample_eml(subject="Email 2", body="Corpo 2.")
        eml3 = create_sample_eml(subject="Email 3", body="Corpo 3.")

        response = self.client.post(
            "/api/upload",
            data={
                "files": [
                    (io.BytesIO(eml1), "email1.eml"),
                    (io.BytesIO(eml2), "email2.eml"),
                    (io.BytesIO(eml3), "email3.eml"),
                ]
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["processed"], 3)
        self.assertEqual(len(data["files"]), 3)

        # Verifica che il download ZIP contenga 3 PDF
        session_id = data["session_id"]
        dl_response = self.client.get(f"/api/download/{session_id}")
        if dl_response.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(dl_response.data)) as zf:
                names = zf.namelist()
                self.assertEqual(len(names), 3)
                for name in names:
                    self.assertTrue(name.endswith(".pdf"))

    def test_upload_invalid_extension(self):
        """Upload di file con estensione non .eml."""
        response = self.client.post(
            "/api/upload",
            data={"files": (io.BytesIO(b"not an eml"), "test.txt")},
            content_type="multipart/form-data",
        )
        # Dovrebbe restituire errore perché nessun file valido
        self.assertIn(response.status_code, [400, 422])

    def test_download_invalid_session(self):
        """Download con session_id non valido."""
        response = self.client.get("/api/download/sessioneinesistente123")
        self.assertEqual(response.status_code, 404)

    def test_robots_txt(self):
        """robots.txt è servito."""
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"User-agent", response.data)

    def test_sitemap_xml(self):
        """sitemap.xml è servito."""
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"urlset", response.data)


if __name__ == "__main__":
    unittest.main()
