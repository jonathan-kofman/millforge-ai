"""
Shared PDF processing infrastructure for quality modules.

Used by:
- MTR Reader (#32) — extracting chemistry tables and mechanical properties
- Drawing Reader (#6) — extracting GD&T callouts from engineering drawings
- Logbook (#23) — photo OCR if needed
"""

import hashlib
import io
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("millforge.pdf")


@dataclass
class PDFExtractionResult:
    """Result from PDF text/table extraction."""
    text: str = ""
    tables: list = field(default_factory=list)
    page_count: int = 0
    method: str = "none"  # pdfplumber | ocr | hybrid


class PDFProcessor:
    """PDF text and table extraction with OCR fallback.

    Strategy:
    1. Try pdfplumber (fast, works for digital PDFs)
    2. If extracted text is too short (<50 chars), fall back to pytesseract OCR
    """

    MIN_TEXT_LENGTH = 50  # below this, assume scanned PDF and try OCR

    def extract(self, pdf_bytes: bytes) -> PDFExtractionResult:
        """Extract text and tables from a PDF. Auto-detects scanned vs digital."""
        result = self._extract_pdfplumber(pdf_bytes)
        if len(result.text.strip()) < self.MIN_TEXT_LENGTH:
            ocr_result = self._extract_ocr(pdf_bytes)
            if len(ocr_result.text.strip()) > len(result.text.strip()):
                ocr_result.method = "ocr"
                return ocr_result
            result.method = "pdfplumber_sparse"
        return result

    def extract_text(self, pdf_bytes: bytes) -> str:
        """Extract text only (convenience wrapper)."""
        return self.extract(pdf_bytes).text

    def extract_tables(self, pdf_bytes: bytes) -> list:
        """Extract tables only (convenience wrapper)."""
        return self.extract(pdf_bytes).tables

    def file_hash(self, pdf_bytes: bytes) -> str:
        """SHA-256 hash for deduplication."""
        return hashlib.sha256(pdf_bytes).hexdigest()

    def _extract_pdfplumber(self, pdf_bytes: bytes) -> PDFExtractionResult:
        """Primary extraction via pdfplumber."""
        try:
            import pdfplumber
        except ImportError:
            logger.warning("pdfplumber not installed — PDF text extraction unavailable")
            return PDFExtractionResult(method="unavailable")

        result = PDFExtractionResult(method="pdfplumber")
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                result.page_count = len(pdf.pages)
                text_parts = []
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    text_parts.append(page_text)
                    page_tables = page.extract_tables() or []
                    for table in page_tables:
                        result.tables.append(table)
                result.text = "\n".join(text_parts)
        except Exception as exc:
            logger.error("pdfplumber extraction failed: %s", exc)
        return result

    def _extract_ocr(self, pdf_bytes: bytes) -> PDFExtractionResult:
        """Fallback OCR extraction via pytesseract + pdf2image."""
        result = PDFExtractionResult(method="ocr")
        try:
            from pdf2image import convert_from_bytes
            import pytesseract
        except ImportError:
            logger.warning("pytesseract/pdf2image not installed — OCR unavailable")
            return result

        try:
            images = convert_from_bytes(pdf_bytes, dpi=300)
            result.page_count = len(images)
            text_parts = []
            for img in images:
                text_parts.append(pytesseract.image_to_string(img))
            result.text = "\n".join(text_parts)
        except Exception as exc:
            logger.error("OCR extraction failed: %s", exc)
        return result
