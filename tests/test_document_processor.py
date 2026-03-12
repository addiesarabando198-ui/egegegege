import pytest
from core.document_processor import DocumentProcessor


def test_clean_text_removes_noise_and_normalizes_quotes():
    raw = "  “Test”\n\n\t  text ‘example’  "
    cleaned = DocumentProcessor._clean_text(raw)
    assert cleaned == '"Test" text \'example\''
