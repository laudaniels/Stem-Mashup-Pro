"""Pre-rendered loop buffer for real-time streaming."""

import threading
import time
import logging
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class LoopRenderBuffer:
    """Pre-renders and streams audio loops for real-time playback."""

    def __init__(self, render_func: Callable, loop_duration: int = 20):
        """
        Initialize loop buffer.

        Args:
            render_func: Function that renders audio (settings, duration) -> bytes (MP3)
            loop_duration: Duration of loop to pre-render in seconds
        """
        self.render_func = render_func
        self.loop_duration = loop_duration
        self.loop_buffer = bytearray()
        self.read_pos = 0
        self.is_rendering = False
        self.loop_ready = threading.Event()
        self.lock = threading.Lock()
        self.render_thread: Optional[threading.Thread] = None
        self.running = False
        self.current_version = 0  # Track settings version for re-render detection

    def start_render(self, settings: dict):
        """Start pre-rendering loop with given settings."""
        with self.lock:
            self.loop_ready.clear()
            self.loop_buffer.clear()
            self.read_pos = 0

        logger.info(f"[LoopBuffer] Starting pre-render: {self.loop_duration}s loop")
        self.running = True
        self.is_rendering = True

        # Render loop in background
        self.render_thread = threading.Thread(
            target=self._render_loop,
            args=(settings,),
            daemon=True
        )
        self.render_thread.start()

    def _render_loop(self, settings: dict):
        """Render the full loop audio."""
        try:
            logger.info(f"[LoopBuffer] Rendering {self.loop_duration}s loop...")
            start = time.time()

            # Render full loop
            audio_data = self.render_func(settings, self.loop_duration)

            if audio_data:
                with self.lock:
                    self.loop_buffer = bytearray(audio_data)
                    self.read_pos = 0

                elapsed = time.time() - start
                logger.info(
                    f"[LoopBuffer] ✓ Loop ready: {len(audio_data)} bytes in {elapsed:.1f}s"
                )
                self.loop_ready.set()
            else:
                logger.error("[LoopBuffer] Render returned no data")

        except Exception as e:
            logger.error(f"[LoopBuffer] Render error: {e}", exc_info=True)
        finally:
            self.is_rendering = False

    def read_chunk(self, chunk_size: int = 4096) -> Optional[bytes]:
        """
        Read next chunk from loop buffer (with looping).

        Returns:
            Audio bytes, or None if not ready
        """
        if not self.loop_ready.is_set():
            return None

        with self.lock:
            if not self.loop_buffer:
                return None

            # Read with wraparound
            chunk = bytearray()
            remaining = chunk_size
            buffer_size = len(self.loop_buffer)

            while remaining > 0:
                # How much until end of buffer?
                until_end = buffer_size - self.read_pos
                to_read = min(remaining, until_end)

                # Read from buffer
                chunk.extend(self.loop_buffer[self.read_pos : self.read_pos + to_read])
                self.read_pos += to_read
                remaining -= to_read

                # Wrap around
                if self.read_pos >= buffer_size:
                    self.read_pos = 0
                    logger.debug("[LoopBuffer] Loop wrapped around")

            return bytes(chunk)

    def wait_for_ready(self, timeout: float = 30.0) -> bool:
        """Wait for loop to be ready."""
        return self.loop_ready.wait(timeout=timeout)

    def stop(self):
        """Stop rendering and clean up."""
        self.running = False
        if self.render_thread:
            self.render_thread.join(timeout=2)
        logger.info("[LoopBuffer] Stopped")

    def is_ready(self) -> bool:
        """Check if loop is ready to stream."""
        return self.loop_ready.is_set()

    def get_status(self) -> dict:
        """Get buffer status."""
        return {
            "is_ready": self.is_ready(),
            "is_rendering": self.is_rendering,
            "buffer_size": len(self.loop_buffer),
            "loop_duration": self.loop_duration,
            "current_version": self.current_version,
        }

    def check_and_rerender(self, settings: dict, new_version: int):
        """Check if settings have changed and re-render if needed."""
        if new_version != self.current_version:
            logger.info(f"[LoopBuffer] Settings changed (v{self.current_version} → v{new_version}), re-rendering...")
            self.current_version = new_version
            self.start_render(settings)
            return True
        return False
