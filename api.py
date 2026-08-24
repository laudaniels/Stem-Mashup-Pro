"""Flask API for Stem Mashup Pro"""
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from pathlib import Path
import json
import logging
from datetime import datetime
from gradio_app import StudioState

logging.basicConfig(level=logging.DEBUG)

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


@app.route('/loop_current.mp3')
def serve_loop_file():
    """Serve the loop audio file"""
    logging.info(f"Serving loop file from: {BASE_DIR}/loop_current.mp3")
    return send_from_directory(str(BASE_DIR), 'loop_current.mp3')


@app.route('/<path:filepath>')
def serve_files(filepath):
    """Serve static assets or fall back to React routing"""
    # Try serving from frontend dist
    dist_path = Path('frontend/dist') / filepath
    if dist_path.is_file():
        logging.info(f"Serving from dist: {filepath}")
        return send_from_directory('frontend/dist', filepath)

    # Fall back to index.html for React routing
    logging.info(f"File not found: {filepath}, serving index.html for React routing")
    return send_from_directory('frontend/dist', 'index.html')




# ===== API Routes =====
@app.route('/api/load-song/<int:slot>', methods=['POST'])
def load_song(slot):
    """Load a song file"""
    slot = int(slot)  # Convert to int
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
    try:
        logging.info(f"Loading song {slot} from {file_path}")
        # Note: load_song expects (file_path, slot) not (slot, file_path)
        result = state.load_song(str(file_path), slot)
        logging.info(f"Load result: {result}")
        return jsonify({
            'path': str(file_path),
            'name': file.filename,
            'message': result[0]
        })
    except Exception as e:
        logging.error(f"Load failed: {e}", exc_info=True)
        return jsonify({'error': f'Load failed: {str(e)}'}), 500


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

    try:
        logging.info(f"Start loop request: {data}")

        # Update state with current sliders
        state.sliders = data.get('sliders', state.sliders)
        state.crossfader = data.get('crossfader', 50)
        state.target_bpm = data.get('target_bpm', 0)
        state.beatmatch = data.get('beatmatch', False)

        # Start the loop
        loop_start = data.get('loop_start', 0)
        loop_length = data.get('loop_length', '8 bars (20s)')

        logging.info(f"Calling start_loop with: start={loop_start}, length={loop_length}")
        file_path, status = state.start_loop(loop_start, loop_length)
        logging.info(f"Start loop result: file={file_path}, status={status}")

        if not file_path:
            logging.error(f"No file path returned: {status}")
            return jsonify({'error': status}), 500

        # Convert absolute path to relative URL for browser fetching
        relative_url = file_path.replace(str(BASE_DIR), '').lstrip('/')
        logging.info(f"Converted {file_path} to URL: /{relative_url}")

        return jsonify({
            'file': f'/{relative_url}',
            'status': status,
            'message': 'Loop ready!'
        })
    except Exception as e:
        logging.error(f"Start loop error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


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
