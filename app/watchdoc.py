import os
import threading
from pathlib import Path
from typing import Dict

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from app.rag_pipeline import ingest_document_path

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


class DocumentEventHandler(FileSystemEventHandler):
    def __init__(self, state: Dict[str, float], usecase_id: str):
        super().__init__()
        self.state = state
        self.usecase_id = usecase_id
        self.lock = threading.Lock()

    def on_created(self, event):
        self._process(event)

    def on_modified(self, event):
        self._process(event)

    def _process(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return

        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            return

        with self.lock:
            previous = self.state.get(str(path))
            if previous is not None and previous == mtime:
                return
            self.state[str(path)] = mtime

        ingest_document_path(str(path.resolve()), usecase_id=self.usecase_id)


class WatchDocService:
    def __init__(self):
        self.observer = None
        self.watch_path = None
        self.usecase_id = None
        self.file_state: Dict[str, float] = {}

    def start(self, path: str, usecase_id: str) -> Dict:
        watch_path = Path(path).resolve()
        if not watch_path.exists():
            return {"success": False, "message": f"Path not found: {watch_path}"}
        if not watch_path.is_dir():
            return {"success": False, "message": f"Path is not a directory: {watch_path}"}
        if self.observer and self.observer.is_alive():
            return {"success": False, "message": "watchdoc is already running"}

        self.watch_path = str(watch_path)
        self.usecase_id = usecase_id
        handler = DocumentEventHandler(self.file_state, usecase_id=usecase_id)
        self.observer = Observer()
        self.observer.schedule(handler, self.watch_path, recursive=True)
        self.observer.start()
        return {"success": True, "watch_path": self.watch_path, "usecase_id": self.usecase_id}

    def stop(self) -> Dict:
        if not self.observer:
            return {"success": False, "message": "watchdoc is not running"}
        self.observer.stop()
        self.observer.join(timeout=5)
        self.observer = None
        self.usecase_id = None
        return {"success": True}

    def status(self) -> Dict:
        running = bool(self.observer and self.observer.is_alive())
        return {
            "running": running,
            "watch_path": self.watch_path if running else None,
            "usecase_id": self.usecase_id if running else None,
            "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
        }


watchdoc_service = WatchDocService()
