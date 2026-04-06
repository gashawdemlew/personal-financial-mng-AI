import re
from typing import List

from PyPDF2 import PdfReader
from docx import Document
import io
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import CHUNK_SIZE, CHUNK_OVERLAP

def extract_text_from_upload(file) -> str:
    filename = (file.filename or "").lower()
    contents = file.file.read()
    file.file.seek(0)
    return extract_text_from_bytes(filename, contents)

def extract_text_from_bytes(filename: str, contents: bytes) -> str:
    if filename.endswith(".txt"):
        return contents.decode("utf-8", errors="ignore")
    if filename.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(contents))
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        return text
    if filename.endswith(".docx"):
        doc = Document(io.BytesIO(contents))
        return "\n".join([p.text for p in doc.paragraphs])
    raise ValueError("Unsupported file format")

def extract_text_from_path(path: str) -> str:
    with open(path, "rb") as f:
        contents = f.read()
    return extract_text_from_bytes(path.lower(), contents)


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_text(text: str) -> List[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text)
