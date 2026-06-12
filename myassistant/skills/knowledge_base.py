"""Local knowledge base — ingest files from a folder, search them semantically.

All data stays on-device: embeddings and chunks live in the existing SQLite
vector store. No cloud storage, no external vector DB.

Supported file types: .txt .md .pdf .docx .csv .json .py .js .ts .html
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from myassistant.core import vector_memory as vm
from myassistant.core.registry import skill

_CHUNK_SIZE = 800      # chars per chunk
_CHUNK_OVERLAP = 150   # overlap between chunks
_KIND = "kb_doc"


# ── text extraction ───────────────────────────────────────────────────────────

def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix in (".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sh"):
            return path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".json":
            raw = path.read_text(encoding="utf-8", errors="ignore")
            try:
                return json.dumps(json.loads(raw), indent=2)
            except Exception:
                return raw
        if suffix == ".csv":
            return path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(str(path))
                return "\n".join(p.extract_text() or "" for p in reader.pages)
            except ImportError:
                try:
                    import pdfplumber
                    with pdfplumber.open(str(path)) as pdf:
                        return "\n".join(p.extract_text() or "" for p in pdf.pages)
                except ImportError:
                    return f"[PDF: install pypdf or pdfplumber to extract text from {path.name}]"
        if suffix == ".docx":
            try:
                import docx
                doc = docx.Document(str(path))
                return "\n".join(p.text for p in doc.paragraphs)
            except ImportError:
                return f"[DOCX: install python-docx to extract text from {path.name}]"
    except Exception as e:
        return f"[ERROR reading {path.name}: {e}]"
    return ""


def _chunk(text: str, source: str) -> list[str]:
    """Split text into overlapping chunks, prepending source filename."""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    chunks = []
    start = 0
    while start < len(text):
        end = start + _CHUNK_SIZE
        chunk = text[start:end]
        chunks.append(f"[{source}]\n{chunk}")
        start += _CHUNK_SIZE - _CHUNK_OVERLAP
    return chunks


def _file_hash(path: Path) -> str:
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def _already_indexed(path: Path) -> bool:
    """Check if this file (by path+hash) is already in the vector store."""
    file_id = str(path.resolve())
    current_hash = _file_hash(path)
    from myassistant.core.memory import db
    from myassistant.core.vector_memory import VectorEntry
    with db() as s:
        row = s.query(VectorEntry).filter(
            VectorEntry.kind == _KIND,
            VectorEntry.ref_id == file_id,
        ).first()
        if not row:
            return False
        meta = json.loads(row.metadata_json or "{}")
        return meta.get("hash") == current_hash


def _delete_file_chunks(path: Path) -> int:
    file_id = str(path.resolve())
    from myassistant.core.memory import db
    from myassistant.core.vector_memory import VectorEntry
    with db() as s:
        deleted = s.query(VectorEntry).filter(
            VectorEntry.kind == _KIND,
            VectorEntry.ref_id == file_id,
        ).delete()
    return deleted


# ── skills ────────────────────────────────────────────────────────────────────

def _ingest_file(path: Path, folder: Path, force: bool) -> tuple[str, str]:
    """Process a single file. Returns ('indexed'|'skipped'|'error', message)."""
    try:
        if not force and _already_indexed(path):
            return ("skipped", "")
        if force:
            _delete_file_chunks(path)
        text = _extract_text(path)
        if not text.strip():
            return ("skipped", "")
        chunks = _chunk(text, path.name)
        file_id = str(path.resolve())
        file_hash = _file_hash(path)
        meta = {
            "hash": file_hash,
            "path": str(path),
            "filename": path.name,
            "folder": str(folder),
            "indexed_at": time.time(),
        }
        for chunk in chunks:
            vm.add(_KIND, chunk, ref_id=file_id, metadata=meta)
        return ("indexed", path.name)
    except Exception as e:
        return ("error", f"{path.name}: {e}")


@skill(
    name="kb_ingest",
    description=(
        "Index a folder of files into the local knowledge base for semantic search. "
        "folder_path is required. Always recurses all subfolders. Uses up to 20 parallel "
        "threads. Skips already-indexed unchanged files. Returns a summary of what was indexed."
    ),
)
def kb_ingest(folder_path: str, force: bool = False, threads: int = 20) -> str:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    folder = Path(folder_path).expanduser().resolve()
    if not folder.exists():
        return f"ERROR: folder not found: {folder}"
    if not folder.is_dir():
        return f"ERROR: not a directory: {folder}"

    extensions = {
        ".txt", ".md", ".pdf", ".docx", ".csv", ".json",
        ".py", ".js", ".ts", ".html", ".css", ".yaml", ".yml",
        ".toml", ".ini", ".cfg", ".sh",
    }

    files = [f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in extensions]

    if not files:
        return f"No supported files found in {folder} (searched all subdirectories)"

    indexed, skipped, errors = 0, 0, []
    max_workers = min(threads, 20, len(files))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_ingest_file, f, folder, force): f for f in files}
        for future in as_completed(futures):
            status, msg = future.result()
            if status == "indexed":
                indexed += 1
            elif status == "skipped":
                skipped += 1
            else:
                errors.append(msg)

    parts = [f"✅ Indexed {indexed} file(s), skipped {skipped} unchanged ({len(files)} total found)."]
    if errors:
        parts.append(f"⚠️ {len(errors)} error(s): {'; '.join(errors[:5])}")
    parts.append(f"Folder: {folder}")
    return "\n".join(parts)


@skill(
    name="kb_search",
    description=(
        "Semantic search across the local knowledge base built from ingested files. "
        "Returns the most relevant passages with source filenames."
    ),
)
def kb_search(query: str, k: int = 5) -> str:
    results = vm.search(query, kind=_KIND, k=k)
    if not results:
        return "No results found. Has the folder been indexed with kb_ingest?"
    out = []
    for r in results:
        meta = {}
        try:
            from myassistant.core.memory import db
            from myassistant.core.vector_memory import VectorEntry
            with db() as s:
                row = s.query(VectorEntry).filter(
                    VectorEntry.kind == _KIND,
                    VectorEntry.text == r["text"],
                ).first()
                if row:
                    meta = json.loads(row.metadata_json or "{}")
        except Exception:
            pass
        filename = meta.get("filename", r.get("ref_id", "?"))
        out.append(f"[{filename} — score {r['score']:.2f}]\n{r['text'][:400]}")
    return "\n\n---\n\n".join(out)


@skill(
    name="kb_status",
    description="Show how many files and chunks are in the local knowledge base.",
)
def kb_status() -> str:
    from myassistant.core.memory import db
    from myassistant.core.vector_memory import VectorEntry
    with db() as s:
        total_chunks = s.query(VectorEntry).filter(VectorEntry.kind == _KIND).count()
        # Count unique files
        files = s.query(VectorEntry.ref_id).filter(
            VectorEntry.kind == _KIND
        ).distinct().all()
    n_files = len(files)
    if n_files == 0:
        return "Knowledge base is empty. Use kb_ingest to index a folder."
    return f"Knowledge base: {n_files} file(s), {total_chunks} chunk(s) indexed locally."


@skill(
    name="kb_clear",
    description="Remove all indexed documents from the local knowledge base.",
)
def kb_clear(confirm: bool = False) -> str:
    if not confirm:
        return "Pass confirm=true to wipe the knowledge base."
    from myassistant.core.memory import db
    from myassistant.core.vector_memory import VectorEntry
    with db() as s:
        deleted = s.query(VectorEntry).filter(VectorEntry.kind == _KIND).delete()
    return f"Cleared {deleted} chunks from the knowledge base."
