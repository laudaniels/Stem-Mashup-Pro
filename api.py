"""Flask API for Stem Mashup Pro"""
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from pathlib import Path
import json
from datetime import datetime
from gradio_app import StudioState

app = Flask(__name__, static_folder='frontend/dist', static_url_path='')
CORS(app)

# Initialize the studio state
state = StudioState()

BASE_DIR = Path(__file__).resolve().parent


# ===== Static Files =====
@app.route('/')
def index():
    """Serve React frontend"""
    return send_from_directory('frontend/dist', 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    """Serve static assets"""
    if path != "" and Path(f'frontend/dist/{path}').is_file():
        return send_from_directory('frontend/dist', path)
    return send_from_directory('frontend/dist', 'index.html')


# ===== API Routes =====
@app.route('/api/load-song/<int:slot>', methods=['POST'])
def load_song(slot):
    """Load a song file"""
    if slot not in [0, 1]:
        return jsonify({'error': 'Invalid slot'}), 400

    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400

    # Save to Audio directory
    audio_dir = BASE_DIR / 'Audio'
    audio_dir.mkdir(exist_ok=True)

    file_path = audio_dir / file.filename
    file.save(str(file_path))

    # Load the song
    result = state.load_song(slot, str(file_path))

    return jsonify({
        'path': str(file_path),
        'name': file.filename,
        'message': result[0]
    })


@app.route('/api/status')
def get_status():
    """Get current status"""
    return jsonify({
        'songs_loaded': [bool(p) for p in state.song_paths],
        'stems_ready': state.both_songs_loaded() and all(state.stem_paths),
        'stems': state.stem_paths,
        'bpms': state.song_bpms,
        'status_messages': state.status_messages[-5:] if state.status_messages else []
    })


@app.route('/api/start-loop', methods=['POST'])
def start_loop():
    """Start loop rendering with current settings"""
    data = request.json

    # Update state with current sliders
    state.sliders = data.get('sliders', state.sliders)
    state.crossfader = data.get('crossfader', 50)
    state.target_bpm = data.get('target_bpm', 0)
    state.beatmatch = data.get('beatmatch', False)

    # Start the loop
    loop_start = data.get('loop_start', 0)
    loop_length = data.get('loop_length', '8 bars (20s)')

    file_path, status = state.start_loop(loop_start, loop_length)

    if not file_path:
        return jsonify({'error': status}), 500

    return jsonify({
        'file': file_path,
        'status': status,
        'message': 'Loop ready!'
    })


@app.route('/api/stop-loop', methods=['POST'])
def stop_loop():
    """Stop loop playback"""
    state.loop_active = False
    return jsonify({'status': 'Loop stopped'})


@app.route('/api/render', methods=['POST'])
def render_final():
    """Render final mix"""
    try:
        file_path = state.render()
        if not file_path:
            return jsonify({'error': 'Render failed'}), 500

        return jsonify({
            'file': file_path,
            'message': 'Render complete!'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ===== Health Check =====
@app.route('/api/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
