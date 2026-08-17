"""Manager for coordinating Gradio UI with audio streaming server."""

import threading
import logging
from typing import Optional, Callable
from pathlib import Path
from audio_state import AudioStreamState
from audio_server import AudioStreamServer
from audio_render_thread import AudioRenderThread

logger = logging.getLogger(__name__)


class AudioStreamManager:
    """Manages real-time audio streaming between Gradio and render thread."""

    def __init__(
        self,
        render_func: Callable,
        server_port: int = 5001,
        buffer_size_mb: int = 5,
        chunk_duration: int = 10,
    ):
        """
        Initialize audio stream manager.

        Args:
            render_func: Function to render audio (settings, duration) -> bytes
            server_port: Port for Flask server
            buffer_size_mb: Circular buffer size in MB
            chunk_duration: Duration of each render chunk in seconds
        """
        self.render_func = render_func
        self.server_port = server_port
        self.chunk_duration = chunk_duration

        # Create shared state
        buffer_size_bytes = buffer_size_mb * 1024 * 1024
        self.state = AudioStreamState(audio_buffer=bytearray(buffer_size_bytes))

        # Server and thread (created on demand)
        self.server: Optional[AudioStreamServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.render_thread: Optional[AudioRenderThread] = None

        self.is_running = False

    def start(self) -> str:
        """
        Start audio streaming server and render thread.

        Returns:
            Stream URL for audio player
        """
        if self.is_running:
            logger.warning("Audio streaming already running")
            return self.get_stream_url()

        try:
            # Create Flask server
            self.server = AudioStreamServer(self.state, self.server_port)
            self.server_thread = threading.Thread(target=self.server.run, daemon=True)
            self.server_thread.start()
            logger.info("Audio server started")

            # Wait a moment for server to be ready
            import time
            time.sleep(0.5)

            # Create and start render thread
            self.render_thread = AudioRenderThread(
                self.state,
                self.render_func,
                self.chunk_duration,
                daemon=True,
            )
            self.render_thread.start()
            logger.info("Render thread started")

            self.is_running = True
            return self.get_stream_url()

        except Exception as e:
            logger.error(f"Error starting audio streaming: {e}", exc_info=True)
            self.stop()
            raise

    def stop(self):
        """Stop audio streaming server and render thread."""
        if not self.is_running:
            return

        try:
            if self.render_thread:
                self.render_thread.stop()

            if self.server:
                self.server.stop()

            self.is_running = False
            logger.info("Audio streaming stopped")

        except Exception as e:
            logger.error(f"Error stopping audio streaming: {e}")

    def get_stream_url(self) -> str:
        """Get the stream URL for the audio player."""
        return f"http://localhost:{self.server_port}/audio/stream"

    def update_settings(self, settings: dict):
        """
        Update audio settings and trigger re-render.

        Args:
            settings: Dictionary of current slider values
        """
        if not self.is_running:
            logger.debug("Stream not running, skipping settings update")
            return

        try:
            with self.state.lock:
                self.state.current_settings = settings
                self.state.render_version += 1
                self.state.settings_changed.set()

            logger.debug(f"Settings updated (v{self.state.render_version})")

        except Exception as e:
            logger.error(f"Error updating settings: {e}")

    def get_status(self) -> dict:
        """Get streaming status info."""
        return {
            "is_running": self.is_running,
            "buffer_duration": self.state.get_buffer_duration(),
            "render_version": self.state.render_version,
            "stream_url": self.get_stream_url() if self.is_running else None,
        }
