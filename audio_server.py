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

    def __init__(self, audio_state: AudioStreamState, port: int = 5001):
        self.app = Flask(__name__)
        CORS(self.app)  # Enable CORS for Gradio communication

        self.state = audio_state
        self.port = port
        self.running = False

        # Register routes
        self.app.add_url_rule("/audio/stream", "stream_audio", self.stream_audio)
        self.app.add_url_rule("/settings", "update_settings", self.update_settings, methods=["POST"])
        self.app.add_url_rule("/health", "health_check", self.health_check)

    def stream_audio(self):
        """HTTP streaming endpoint for audio player."""
        chunk_size = 4096  # 4KB chunks
        buffer_timeout = 5  # seconds to wait for buffer data

        def generate():
            """Generator function for Flask streaming."""
            while self.running:
                # Wait for data to be available in buffer
                start_time = time.time()
                while len(self.state.audio_buffer) == 0 and self.running:
                    if time.time() - start_time > buffer_timeout:
                        # Timeout waiting for data
                        logger.warning("Timeout waiting for audio buffer")
                        yield b""
                        continue

                    time.sleep(0.01)  # Small sleep to avoid busy waiting

                if not self.running:
                    break

                # Read chunk from buffer
                chunk = self.state.read_chunk(chunk_size)
                if chunk:
                    yield chunk
                else:
                    time.sleep(0.01)

        return Response(generate(), mimetype="audio/mpeg")

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
