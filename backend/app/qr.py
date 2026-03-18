from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .storage import StorageProvider


@dataclass(slots=True)
class QRJob:
    job_id: str
    status: str
    progress: int
    pdf_bytes: bytes | None = None
    error: str | None = None


class QRJobManager:
    def __init__(self, storage: StorageProvider) -> None:
        self.storage = storage
        self.storage_backend_label = storage.qr_pdf_backend_label()
        self._jobs: dict[str, QRJob] = {}
        self._lock = Lock()

    def create_job(self, count: int) -> QRJob:
        job_id = uuid4().hex
        job = QRJob(job_id=job_id, status="running", progress=0)
        with self._lock:
            self._jobs[job_id] = job
        asyncio.create_task(self._generate(job_id, count))
        return job

    def get_job(self, job_id: str) -> QRJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    async def _generate(self, job_id: str, count: int) -> None:
        try:
            refs: list[str] = []
            for i in range(count):
                refs.append(self.storage.create_storage_for_user())
                self._update_progress(job_id, int(((i + 1) / count) * 80))

            pdf = await asyncio.to_thread(self._build_pdf, refs)
            with self._lock:
                job = self._jobs[job_id]
                job.pdf_bytes = pdf
                job.progress = 100
                job.status = "done"
        except Exception as exc:  # pragma: no cover - defensive
            with self._lock:
                job = self._jobs[job_id]
                job.status = "failed"
                job.error = str(exc)

    def _update_progress(self, job_id: str, value: int) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.progress = max(0, min(100, value))

    def _build_pdf(self, refs: list[str]) -> bytes:
        buf = io.BytesIO()
        pdf = canvas.Canvas(buf, pagesize=A4)

        page_width, page_height = A4
        cols = 6
        items_per_page = 48
        rows = (items_per_page + cols - 1) // cols

        header_margin_x = 24
        header_top_y = page_height - 24
        grid_margin_x = 24
        grid_bottom_y = 24
        grid_top_y = page_height - 92
        horizontal_gap = 8
        vertical_gap = 12

        usable_width = page_width - (2 * grid_margin_x) - ((cols - 1) * horizontal_gap)
        usable_height = grid_top_y - grid_bottom_y - ((rows - 1) * vertical_gap)
        qr_size = min(usable_width / cols, usable_height / rows)

        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        pdf.setTitle("Teddy Hospital QR Codes")
        for page_start in range(0, len(refs), items_per_page):
            if page_start > 0:
                pdf.showPage()
            self._draw_page_header(
                pdf=pdf,
                margin_x=header_margin_x,
                top_y=header_top_y,
                page_width=page_width,
                generated_at=generated_at,
            )

            for offset, ref in enumerate(
                refs[page_start : page_start + items_per_page]
            ):
                row = offset // cols
                col = offset % cols
                x = grid_margin_x + col * (qr_size + horizontal_gap)
                y = grid_top_y - qr_size - row * (qr_size + vertical_gap)

                qr = qrcode.QRCode(version=1, box_size=6, border=2)
                qr.add_data(ref)
                qr.make(fit=True)
                image = qr.make_image(
                    fill_color="black", back_color="white"
                ).get_image()
                pdf.drawInlineImage(image, x, y, width=qr_size, height=qr_size)

        pdf.save()
        return buf.getvalue()

    def _draw_page_header(
        self,
        pdf: canvas.Canvas,
        margin_x: float,
        top_y: float,
        page_width: float,
        generated_at: str,
    ) -> None:
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(margin_x, top_y, "Teddy Hospital QR Batch")
        pdf.setFont("Helvetica", 9)
        pdf.drawString(
            margin_x, top_y - 14, f"Storage backend: {self.storage_backend_label}"
        )
        pdf.drawString(margin_x, top_y - 27, f"Generated: {generated_at}")
        pdf.line(margin_x, top_y - 34, page_width - margin_x, top_y - 34)
