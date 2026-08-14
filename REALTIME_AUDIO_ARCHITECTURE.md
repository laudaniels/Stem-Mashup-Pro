# Real-Time Audio Streaming Architecture

## Overview
Enable users to listen to mixes in real-time as they adjust settings. When stems finish separating, automatically generate a preview mix that updates as settings change.

## System Components

### 1. Audio Streaming Server (Flask/FastAPI)
**Purpose:** Serve audio chunks to the Gradio frontend in real-time

```
┌─────────────────────────────────────────────────────────────┐
│  Audio Streaming Server (Port 5001)                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  GET /audio/stream?version=X                                │
│  └─ Streams audio in chunks (e.g., MP3 HTTP streaming)     │
│                                                              │
│  POST /settings (receives updated slider values)            │
│  └─ Triggers re-render with new settings                   │
│                                                              │
│  WebSocket /ws/settings                                     │
│  └─ Real-time bidirectional settings sync (alternative)    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 2. Audio Render Pipeline
**Purpose:** Continuously render audio based on current settings

```
┌──────────────────────────────────────────────────────┐
│ Background Render Thread                            │
├──────────────────────────────────────────────────────┤
│                                                      │
│  1. Get current settings from shared state         │
│  2. Render 10-30 second chunk with mashup_engine  │
│  3. Write to circular buffer                       │
│  4. If settings changed during render:             │
│     → Stop current render                          │
│     → Start new render with updated settings       │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### 3. Shared State Management
**Purpose:** Thread-safe communication between Gradio UI and render thread

```python
class AudioStreamState:
    current_settings: dict  # All slider values, locks
    render_version: int     # Increments when settings change
    audio_buffer: bytes     # Circular buffer of rendered audio
    is_playing: bool
    playback_position: float
    settings_changed: Event  # Signals render thread to restart
```

### 4. Audio Buffer (Circular)
**Purpose:** Hold pre-rendered audio chunks for streaming

```
┌─────────────────────────────────────────┐
│  Circular Audio Buffer (10-30 seconds)  │
├─────────────────────────────────────────┤
│  Write Head  ─────┐                    │
│                   │                    │
│  [████████████░░░░░░░░░░░░░░░░░░]      │
│           ↑                      ↑      │
│           │                      │      │
│      Read Head          Buffer Wrap    │
│                                        │
│  Render thread writes → Read thread ← Player reads
└─────────────────────────────────────────┘
```

## Data Flow

### Scenario 1: Stems Analysis Complete
```
1. load_song() finishes stem separation
2. Trigger event: "stems_ready"
3. Create AudioStreamState with initial settings
4. Start background render thread
5. Render thread generates audio continuously
6. Update output_audio player with stream URL
7. User can click play whenever ready
```

### Scenario 2: User Adjusts a Slider (While Playing)
```
1. Slider change event fires in Gradio
2. Update shared AudioStreamState.current_settings
3. Increment AudioStreamState.render_version
4. Set AudioStreamState.settings_changed event
5. Background thread detects change:
   a. Stops current render
   b. Clears buffer
   c. Starts new render with new settings
6. Player continues reading from buffer (might briefly stall)
7. New audio reflects settings change after ~500ms-1s
```

### Scenario 3: User Stops and Restarts Player
```
1. Player.stop() → record current AudioStreamState.render_version
2. Player.play() → render thread continues with current settings
3. Fresh audio starts from buffer beginning with settings at play time
```

## Implementation Details

### Part A: Flask Audio Server
**File:** `audio_server.py`

```python
from flask import Flask, send_file, request
from threading import Thread, Event, Lock
import io
import time

app = Flask(__name__)

class AudioBuffer:
    def __init__(self, size_bytes=5242880):  # 5MB buffer
        self.buffer = bytearray(size_bytes)
        self.write_pos = 0
        self.read_pos = 0
        self.lock = Lock()
    
    def write_chunk(self, data):
        """Write audio chunk to buffer, wrap around if needed"""
        # Circular write logic
        pass
    
    def read_chunk(self, start_pos, size):
        """Read chunk from buffer for HTTP streaming"""
        # Circular read logic
        pass

class RenderThread(Thread):
    def __init__(self, state, buffer):
        self.state = state
        self.buffer = buffer
        self.running = True
        self.render_version = -1
    
    def run(self):
        """Continuously render audio based on current settings"""
        while self.running:
            # Check if settings changed
            if self.state.render_version > self.render_version:
                self.render_version = self.state.render_version
                self.buffer.clear()
            
            # Render next chunk (10 seconds)
            settings = self.state.current_settings.copy()
            audio_chunk = render_mix(settings, duration=10)
            self.buffer.write_chunk(audio_chunk)
            
            time.sleep(0.1)  # Prevent CPU spinning

@app.route('/audio/stream')
def stream_audio():
    """HTTP streaming endpoint for audio player"""
    # Return audio stream that player can consume
    # Use HTTP Range requests for seeking
    pass

@app.route('/settings', methods=['POST'])
def update_settings():
    """Receive updated settings from Gradio"""
    settings = request.json
    with audio_state.lock:
        audio_state.current_settings = settings
        audio_state.render_version += 1
    return {'status': 'ok'}
```

### Part B: Gradio Integration
**File:** `gradio_app.py` (modifications)

```python
def create_app():
    # ... existing code ...
    
    # Create audio stream state
    audio_stream_state = AudioStreamState()
    
    def on_stems_ready():
        """Callback when stem separation completes"""
        if state.stems_ready():
            # Initialize stream with current settings
            audio_stream_state.current_settings = {
                's0_volume': state.sliders['s0_volume'],
                's1_volume': state.sliders['s1_volume'],
                # ... all other settings
            }
            audio_stream_state.render_version = 0
            
            # Return stream URL to output player
            return "http://localhost:5001/audio/stream?v=0"
    
    # Volume sliders with settings sync
    with gr.Row():
        volume_s0 = gr.Slider(label="Song 1 Volume")
        
        def on_volume_change(value):
            audio_stream_state.current_settings['s0_volume'] = value
            audio_stream_state.render_version += 1
            return value
        
        volume_s0.change(
            on_volume_change,
            inputs=[volume_s0],
            outputs=[volume_s0]
        )
```

### Part C: Browser Audio Player Integration
**Option 1: HTML5 Audio with HTTP Streaming (Recommended)**
```html
<audio id="player" controls>
    <source src="http://localhost:5001/audio/stream" type="audio/mpeg">
</audio>
```

**Option 2: WebSocket with Web Audio API (More Complex)**
- Use JavaScript Web Audio API
- Connect via WebSocket to receive audio chunks
- Decode and play using AudioContext
- Enables more control but higher complexity

## Technical Challenges & Solutions

### Challenge 1: Audio Discontinuities When Settings Change
**Problem:** Changing settings mid-playback creates pops/clicks

**Solutions:**
- Fade out/in during transition (100ms envelope)
- Buffer overlap: render 1 second overlap between old/new settings
- Use audio crossfading

### Challenge 2: Buffer Management
**Problem:** Circular buffer edge cases, sync issues

**Solutions:**
- Use thread-safe queue (Python `queue.Queue`)
- Double-buffering (two buffers, alternate writes/reads)
- Pre-allocate fixed-size buffer

### Challenge 3: Seeking in Stream
**Problem:** User seeks in player, need to provide correct audio chunk

**Solutions:**
- Use HTTP Range requests
- Track playback position
- Render audio starting from seek position

### Challenge 4: CPU Usage
**Problem:** Continuous rendering at full quality = high CPU

**Solutions:**
- Lower quality during playback (44.1kHz instead of 48kHz)
- Increase chunk size (30 seconds instead of 10)
- Use lower bitrate MP3
- Profile and optimize render pipeline

### Challenge 5: Latency
**Problem:** Settings change → buffer clear → 1-2 second delay

**Solutions:**
- Keep overlapping buffers with different settings
- Predict user changes (pre-render likely next states)
- Accept trade-off: 500ms-1s delay is acceptable UX

## Implementation Phases

### Phase 1: Basic Auto-Preview (Week 1)
- [x] When stems ready → auto-render with current settings
- [x] Display in output player
- [x] Manual refresh when settings change

### Phase 2: Real-Time Buffer (Week 2)
- [ ] Add Flask streaming server
- [ ] Implement circular audio buffer
- [ ] Background render thread
- [ ] Settings synchronization

### Phase 3: Seamless Updates (Week 3)
- [ ] Fade transitions when settings change
- [ ] Zero-crossing detection to avoid clicks
- [ ] Optimize CPU usage

### Phase 4: Advanced Features (Week 4+)
- [ ] Seeking support
- [ ] Lower quality preview mode
- [ ] Settings undo/redo
- [ ] Record/save playback session

## File Structure
```
stem-mashup-pro/
├── gradio_app.py              (modify: add callbacks, stream URL)
├── mashup_engine.py           (no changes needed)
├── audio_server.py            (NEW: Flask streaming server)
├── audio_buffer.py            (NEW: circular buffer implementation)
├── audio_state.py             (NEW: shared state management)
└── requirements.txt           (add: flask, streaming dependencies)
```

## Performance Targets
- Render latency: < 2 seconds for settings change
- CPU usage: < 50% on single core
- Memory: < 200MB buffer + state
- Browser playback: seamless, no stuttering
- Supported browsers: Chrome, Firefox, Safari (HTML5 audio)

## Fallback Strategy
If real-time proves too complex:
1. Keep current manual preview approach
2. Add "Preview" button user clicks after changes
3. Shows ~5 second preview in player
4. User can loop/replay as many times as needed

## Next Steps
1. Review and approve this architecture
2. Estimate implementation effort
3. Break down Phase 2 into concrete tasks
4. Start with Flask server skeleton
