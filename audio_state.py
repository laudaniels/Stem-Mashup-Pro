"""Shared state for audio streaming between Gradio and render thread."""

from threading import Lock, Event
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AudioStreamState:
    """Thread-safe state for real-time audio streaming."""

    # Settings from UI sliders
    current_settings: dict = field(default_factory=dict)

    # Version counter - increments when settings change
    render_version: int = 0

    # Audio buffer management
    audio_buffer: bytearray = field(default_factory=bytearray)
    write_pos: int = 0
    read_pos: int = 0

    # Playback state
    is_playing: bool = False
    playback_position: float = 0.0  # in seconds

    # Thread synchronization
    lock: Lock = field(default_factory=Lock)
    settings_changed: Event = field(default_factory=Event)
    stop_render: Event = field(default_factory=Event)

    # Audio properties
    sample_rate: int = 44100
    channels: int = 2
    bytes_per_sample: int = 2  # 16-bit

    def get_buffer_duration(self) -> float:
        """Calculate current buffer duration in seconds."""
        if self.sample_rate == 0:
            return 0.0
        bytes_per_second = self.sample_rate * self.channels * self.bytes_per_sample
        return len(self.audio_buffer) / bytes_per_second

    def clear_buffer(self):
        """Clear the audio buffer."""
        with self.lock:
            self.audio_buffer.clear()
            self.write_pos = 0
            self.read_pos = 0

    def write_chunk(self, data: bytes):
        """Write audio chunk to circular buffer."""
        if not data:
            return

        with self.lock:
            buffer_size = len(self.audio_buffer)
            if buffer_size == 0:
                return

            data_len = len(data)
            remaining = buffer_size - self.write_pos

            if remaining >= data_len:
                # Write doesn't wrap
                self.audio_buffer[self.write_pos : self.write_pos + data_len] = data
                self.write_pos = (self.write_pos + data_len) % buffer_size
            else:
                # Write wraps around
                self.audio_buffer[self.write_pos :] = data[:remaining]
                self.audio_buffer[: data_len - remaining] = data[remaining:]
                self.write_pos = data_len - remaining

    def read_chunk(self, size: int) -> bytes:
        """Read chunk from circular buffer."""
        with self.lock:
            buffer_size = len(self.audio_buffer)
            if buffer_size == 0:
                return b""

            remaining = buffer_size - self.read_pos

            if remaining >= size:
                # Read doesn't wrap
                chunk = bytes(self.audio_buffer[self.read_pos : self.read_pos + size])
                self.read_pos = (self.read_pos + size) % buffer_size
                return chunk
            else:
                # Read wraps around
                chunk = bytes(self.audio_buffer[self.read_pos :])
                chunk += bytes(self.audio_buffer[: size - remaining])
                self.read_pos = size - remaining
                return chunk
