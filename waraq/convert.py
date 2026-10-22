"""Conversions and features that rely on optional external tools/libraries.

- Office -> PDF : Microsoft Office (Windows, via COM) or LibreOffice (soffice)
- PDF -> Word   : pdf2docx
- OCR           : Tesseract OCR (with Arabic + English language data)
- Digital sign  : pyHanko (PKCS#12 .pfx/.p12 certificates, optional RFC3161 timestamp)
- Scan          : Windows Image Acquisition (WIA) via pywin32
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

import pymupdf as fitz

IS_WIN = sys.platform.startswith("win")


# ------------------------------------------------------------ Office -> PDF
def find_soffice():
    p = shutil.which("soffice") or shutil.which("libreoffice")
    if p:
        return p
    if IS_WIN:
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            for c in glob.glob(os.path.join(base, "LibreOffice*", "program", "soffice.exe")):
                return c
    return None


def _office_com(path, out):
    import win32com.client  # pywin32
    ext = os.path.splitext(path)[1].lower()
    path = os.path.abspath(path)
    out = os.path.abspath(out)
    if ext in (".doc", ".docx", ".rtf", ".odt", ".txt"):
        app = win32com.client.DispatchEx("Word.Application")
        app.Visible = False
        try:
            d = app.Documents.Open(path, ReadOnly=True)
            d.ExportAsFixedFormat(out, 17)
            d.Close(False)
        finally:
            app.Quit()
    elif ext in (".xls", ".xlsx", ".csv", ".ods"):
        app = win32com.client.DispatchEx("Excel.Application")
        app.Visible = False
        app.DisplayAlerts = False
        try:
            wb = app.Workbooks.Open(path, ReadOnly=True)
            wb.ExportAsFixedFormat(0, out)
            wb.Close(False)
        finally:
            app.Quit()
    elif ext in (".ppt", ".pptx", ".odp"):
        app = win32com.client.DispatchEx("PowerPoint.Application")
        try:
            pr = app.Presentations.Open(path, WithWindow=False)
            pr.SaveAs(out, 32)
            pr.Close()
        finally:
            app.Quit()
    else:
        raise RuntimeError("Unsupported Office type")
    return out


def office_to_pdf(path):
    """Returns the path of a temporary PDF."""
    tmpdir = tempfile.mkdtemp(prefix="waraq_")
    out = os.path.join(tmpdir, os.path.splitext(os.path.basename(path))[0] + ".pdf")
    errors = []
    if IS_WIN:
        try:
            return _office_com(path, out)
        except Exception as e:  # Office not installed, or pywin32 missing
            errors.append(f"Microsoft Office: {e}")
    so = find_soffice()
    if so:
        r = subprocess.run([so, "--headless", "--convert-to", "pdf", "--outdir", tmpdir, path],
                           capture_output=True, timeout=300,
                           creationflags=0x08000000 if IS_WIN else 0)
        if os.path.exists(out):
            return out
        errors.append("LibreOffice: " + (r.stderr.decode(errors="ignore") or "conversion failed"))
    raise RuntimeError("To convert Office files install Microsoft Office or LibreOffice (free).\n" + "\n".join(errors))


# ------------------------------------------------------------ PDF -> Word
def pdf_to_docx(pdf_path, out_path, pages=None):
    try:
        from pdf2docx import Converter
    except ImportError:
        raise RuntimeError("PDF to Word needs the 'pdf2docx' package (pip install pdf2docx).")
    cv = Converter(pdf_path)
    try:
        cv.convert(out_path, pages=pages)
    finally:
        cv.close()
    return out_path


# ------------------------------------------------------------ OCR
def find_tessdata():
    env = os.environ.get("TESSDATA_PREFIX")
    if env and os.path.isdir(env):
        return env
    cands = []
    if IS_WIN:
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            cands.append(os.path.join(base, "Tesseract-OCR", "tessdata"))
    else:
        cands += glob.glob("/usr/share/tesseract-ocr/*/tessdata") + ["/usr/share/tessdata", "/usr/local/share/tessdata"]
    # bundled next to the app
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    cands.append(os.path.join(here, "tessdata"))
    for c in cands:
        if os.path.isdir(c) and glob.glob(os.path.join(c, "*.traineddata")):
            return c
    try:
        return fitz.get_tessdata()
    except Exception:
        return None


def ocr_languages():
    td = find_tessdata()
    if not td:
        return []
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(td, "*.traineddata"))
                  if not os.path.basename(p).startswith("osd"))


def ocr_document(doc, language="ara+eng", dpi=300, pages=None, progress=None, skip_text_pages=True):
    """Return a NEW searchable PDF: each scanned page gets an invisible text layer."""
    td = find_tessdata()
    if not td:
        raise RuntimeError("Tesseract OCR is not installed.\nInstall it from https://github.com/UB-Mannheim/tesseract/wiki "
                           "and tick the Arabic language during setup.")
    out = fitz.open()
    pages = list(pages if pages is not None else range(doc.page_count))
    for k, i in enumerate(range(doc.page_count)):
        page = doc[i]
        if i not in pages or (skip_text_pages and len(page.get_text("text").strip()) > 20):
            out.insert_pdf(doc, from_page=i, to_page=i)
        else:
            pix = page.get_pixmap(dpi=dpi)
            data = pix.pdfocr_tobytes(compress=True, language=language, tessdata=td)
            ocr = fitz.open("pdf", data)
            np_ = out.new_page(width=page.rect.width, height=page.rect.height)
            np_.show_pdf_page(np_.rect, ocr, 0)
            ocr.close()
        if progress and not progress(k + 1, doc.page_count):
            break
    try:
        out.set_toc(doc.get_toc())
    except Exception:
        pass
    return out


# ------------------------------------------------------------ Digital signatures
def make_self_signed_pfx(path, name, password, org="", email="", years=5):
    """Create a self-signed certificate (for internal use / testing)."""
    import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, name)]
    if org:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, org))
    if email:
        attrs.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, email))
    subj = x509.Name(attrs)
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=365 * years))
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
            .sign(key, hashes.SHA256()))
    data = pkcs12.serialize_key_and_certificates(name.encode(), key, cert, None,
                                                 serialization.BestAvailableEncryption(password.encode()))
    with open(path, "wb") as f:
        f.write(data)
    return path


def sign_pdf(in_path, out_path, pfx_path, pfx_password, page=0, box=None, reason="", location="",
             contact="", tsa_url="", field_name=None, visible=True):
    try:
        from pyhanko.sign import signers, timestamps, fields
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.sign.fields import SigFieldSpec
        from pyhanko import stamp
        from pyhanko.pdf_utils import text as phtext
    except ImportError:
        raise RuntimeError("Digital signatures need the 'pyhanko' package (pip install pyhanko).")
    signer = signers.SimpleSigner.load_pkcs12(pfx_path, passphrase=pfx_password.encode() if pfx_password else None)
    if signer is None:
        raise RuntimeError("Could not open the certificate. Check the file and its password.")
    field_name = field_name or "Signature_%d" % (abs(hash(out_path)) % 100000)
    with open(in_path, "rb") as inf:
        w = IncrementalPdfFileWriter(inf, strict=False)
        if visible and box:
            # pyHanko boxes use PDF coordinates (origin bottom-left)
            src = fitz.open(in_path)
            h = src[page].mediabox.height
            src.close()
            x0, y0, x1, y1 = box
            pdf_box = (int(x0), int(h - y1), int(x1), int(h - y0))
            fields.append_signature_field(w, SigFieldSpec(field_name, on_page=page, box=pdf_box))
        else:
            fields.append_signature_field(w, SigFieldSpec(field_name, on_page=page))
        meta = signers.PdfSignatureMetadata(field_name=field_name, reason=reason or None,
                                            location=location or None, contact_info=contact or None)
        ts = timestamps.HTTPTimeStamper(tsa_url) if tsa_url else None
        style = stamp.TextStampStyle(
            stamp_text="Digitally signed by %(signer)s\nDate: %(ts)s" + (f"\nReason: {reason}" if reason else ""),
            border_width=1)
        pdf_signer = signers.PdfSigner(meta, signer=signer, timestamper=ts, stamp_style=style)
        with open(out_path, "wb") as outf:
            pdf_signer.sign_pdf(w, output=outf)
    return out_path


def verify_signatures(path):
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
    except ImportError:
        raise RuntimeError("Signature validation needs the 'pyhanko' package.")
    res = []
    with open(path, "rb") as f:
        r = PdfFileReader(f, strict=False)
        for sig in r.embedded_signatures:
            try:
                st = validate_pdf_signature(sig, ValidationContext(allow_fetching=False))
                res.append(dict(field=sig.field_name, signer=st.signing_cert.subject.human_friendly,
                                intact=st.intact, valid=st.valid, trusted=st.trusted,
                                time=str(st.signer_reported_dt or ""), coverage=str(st.coverage).split(".")[-1],
                                summary=st.summary()))
            except Exception as e:
                res.append(dict(field=sig.field_name, signer="?", intact=False, valid=False, trusted=False,
                                time="", coverage="", summary=str(e)))
    return res


# ------------------------------------------------------------ Scanner (Windows WIA)
def scan_to_images(outdir):
    if not IS_WIN:
        raise RuntimeError("Scanning is available on Windows only.")
    try:
        import win32com.client
    except ImportError:
        raise RuntimeError("Scanning needs the 'pywin32' package.")
    dlg = win32com.client.Dispatch("WIA.CommonDialog")
    files = []
    while True:
        img = dlg.ShowAcquireImage()  # shows the standard Windows scan dialog
        if img is None:
            break
        fn = os.path.join(outdir, f"scan_{len(files) + 1:03d}.{img.FileExtension}")
        if os.path.exists(fn):
            os.remove(fn)
        img.SaveFile(fn)
        files.append(fn)
        break  # one image per dialog; caller can repeat
    return files
