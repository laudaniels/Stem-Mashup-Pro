"""Flask server for real-time audio streaming."""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import threading
import time
import logging
from pathlib import Path
from audio_state import AudioStreamState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AudioStreamServer:
    """Flask server for streaming audio to Gradio frontend."""

    def __init__(self, audio_state: AudioStreamState, port: int = 5001, loop_buffer=None):
        self.app = Flask(__name__)
        CORS(self.app)  # Enable CORS for Gradio communication

        self.state = audio_state
        self.port = port
        self.running = False
        self.loop_buffer = loop_buffer  # Optional loop buffer for Phase 2

        # Register routes
        self.app.add_url_rule("/audio/stream", "stream_audio", self.stream_audio)
        self.app.add_url_rule("/settings", "update_settings", self.update_settings, methods=["POST"])
        self.app.add_url_rule("/health", "health_check", self.health_check)

    def stream_audio(self):
        """HTTP streaming endpoint for audio player."""
        logger.info("Stream requested")

        # If using loop buffer (Phase 2), send the pre-rendered loop once
        if self.loop_buffer:
            buffer_timeout = 10
            logger.info("Streaming from loop buffer")
            if not self.loop_buffer.wait_for_ready(timeout=buffer_timeout):
                logger.warning("Loop buffer not ready in time")
                return Response(b"", status=503)

            # Get complete loop data
            loop_data = bytes(self.loop_buffer.loop_buffer)
            logger.info(f"[Stream] Sending complete loop: {len(loop_data)} bytes")

            # Send as complete file with proper headers
            return Response(
                loop_data,
                mimetype="audio/mpeg",
                headers={
                    "Content-Length": str(len(loop_data)),
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                }
            )

        # Fallback to circular buffer mode (Phase 1)
        def generate():
            """Generator function for Flask streaming."""
            chunk_size = 4096
            buffer_timeout = 10
            chunks_sent = 0
            logger.info("Streaming from circular buffer")

            while self.running:
                # Wait for data to be available in buffer
                start_time = time.time()
                while len(self.state.audio_buffer) == 0 and self.running:
                    elapsed = time.time() - start_time
                    if elapsed > buffer_timeout:
                        logger.warning(f"Timeout waiting for buffer after {elapsed:.1f}s")
                        yield b""
                        return  # Stop streaming if no data

                    time.sleep(0.05)

                if not self.running:
                    break

                # Read chunk from buffer
                chunk = self.state.read_chunk(chunk_size)
                if chunk:
                    chunks_sent += 1
                    yield chunk
                    if chunks_sent % 100 == 0:
                        logger.debug(f"Sent {chunks_sent} chunks, buffer: {len(self.state.audio_buffer)} bytes")
                else:
                    time.sleep(0.01)

            logger.info(f"Stream ended after {chunks_sent} chunks")

        return Response(
            generate(),
            mimetype="audio/mpeg",
            headers={
                "Accept-Ranges": "bytes",
                "Connection": "keep-alive",
                "Transfer-Encoding": "chunked",
            }
        )

    def update_settings(self):
        """Receive updated settings from Gradio."""
        try:
            data = request.json
            if not data:
                return jsonify({"error": "No data"}), 400

            with self.state.lock:
                self.state.current_settings = data
                self.state.render_version += 1
                self.state.settings_changed.set()

            logger.info(f"Settings updated: v{self.state.render_version}")
            return jsonify({"status": "ok", "version": self.state.render_version}), 200

        except Exception as e:
            logger.error(f"Error updating settings: {e}")
            return jsonify({"error": str(e)}), 500

    def health_check(self):
        """Health check endpoint."""
        return jsonify({
            "status": "ok",
            "buffer_duration": self.state.get_buffer_duration(),
            "render_version": self.state.render_version
        }), 200

    def set_loop_buffer(self, loop_buffer):
        """Switch to streaming from loop buffer (Phase 2)."""
        self.loop_buffer = loop_buffer
        logger.info("Server switched to loop buffer mode")

    def run(self):
        """Start the server."""
        self.running = True
        logger.info(f"Starting audio server on port {self.port}")
        self.app.run(host="127.0.0.1", port=self.port, debug=False, use_reloader=False)

    def stop(self):
        """Stop the server."""
        self.running = False
        logger.info("Stopping audio server")


def create_server(audio_state: AudioStreamState, port: int = 5001) -> AudioStreamServer:
    """Factory function to create audio stream server."""
    return AudioStreamServer(audio_state, port)


if __name__ == "__main__":
    # For testing
    state = AudioStreamState(audio_buffer=bytearray(5242880))  # 5MB buffer
    server = create_server(state)
    server.run()
