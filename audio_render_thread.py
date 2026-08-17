"""Background render thread for continuous audio generation."""

import threading
import time
import logging
from typing import Callable, Optional
from audio_state import AudioStreamState

logger = logging.getLogger(__name__)


class AudioRenderThread(threading.Thread):
    """Background thread that continuously renders audio based on current settings."""

    def __init__(
        self,
        state: AudioStreamState,
        render_func: Callable,
        chunk_duration: int = 10,
        daemon: bool = True,
    ):
        """
        Initialize render thread.

        Args:
            state: Shared AudioStreamState
            render_func: Function that renders audio given settings and duration
                        Signature: (settings: dict, duration: int) -> bytes
            chunk_duration: Duration of each render chunk in seconds (default 10s)
            daemon: Run as daemon thread
        """
        super().__init__(daemon=daemon)
        self.state = state
        self.render_func = render_func
        self.chunk_duration = chunk_duration
        self.running = False
        self.current_version = -1

    def run(self):
        """Main render loop."""
        self.running = True
        logger.info("Audio render thread started")

        try:
            while self.running:
                # Check if settings changed
                if self.state.render_version > self.current_version:
                    self.current_version = self.state.render_version
                    self.state.clear_buffer()
                    logger.info(f"Settings changed to v{self.current_version}, cleared buffer")

                # Check for stop signal
                if self.state.stop_render.is_set():
                    self.state.stop_render.clear()
                    break

                try:
                    # Get current settings
                    with self.state.lock:
                        settings = self.state.current_settings.copy()

                    # Render next chunk
                    logger.debug(f"Rendering {self.chunk_duration}s chunk (v{self.current_version})")
                    chunk = self.render_func(settings, self.chunk_duration)

                    if chunk:
                        self.state.write_chunk(chunk)
                        buffer_duration = self.state.get_buffer_duration()
                        logger.debug(f"Chunk written, buffer: {buffer_duration:.1f}s")

                except Exception as e:
                    logger.error(f"Error rendering chunk: {e}", exc_info=True)
                    time.sleep(0.5)  # Back off on error

                # Small sleep to prevent busy waiting
                time.sleep(0.1)

        except Exception as e:
            logger.error(f"Render thread crashed: {e}", exc_info=True)
        finally:
            self.running = False
            logger.info("Audio render thread stopped")

    def stop(self):
        """Signal thread to stop."""
        self.running = False
        self.state.stop_render.set()
        logger.info("Stop signal sent to render thread")

    def wait_for_buffer(self, min_duration: float = 2.0, timeout: float = 30.0) -> bool:
        """
        Wait for buffer to fill to minimum duration.

        Args:
            min_duration: Minimum buffer duration in seconds
            timeout: Maximum time to wait in seconds

        Returns:
            True if buffer reached min_duration, False on timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.state.get_buffer_duration() >= min_duration:
                return True
            time.sleep(0.1)

        logger.warning(f"Timeout waiting for buffer (got {self.state.get_buffer_duration():.1f}s)")
        return False
