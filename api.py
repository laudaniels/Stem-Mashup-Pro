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
    file_path = BASE_DIR / 'loop_current.mp3'
    logging.info(f"GET /loop_current.mp3 - checking: {file_path}")
    logging.info(f"File exists: {file_path.exists()}, size: {file_path.stat().st_size if file_path.exists() else 'N/A'}")

    if not file_path.exists():
        logging.error(f"File not found: {file_path}")
        return '', 404

    try:
        return send_from_directory(str(BASE_DIR), 'loop_current.mp3')
    except Exception as e:
        logging.error(f"Error serving file: {e}", exc_info=True)
        return '', 500


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
@app.route('/api/separate-stems', methods=['POST'])
def separate_stems():
    """Separate audio into stems"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400

    try:
        import shutil
        import time

        # Save uploaded file
        audio_dir = BASE_DIR / 'Audio'
        audio_dir.mkdir(exist_ok=True)

        file_path = audio_dir / file.filename
        file.save(str(file_path))
        logging.info(f"Processing stems for: {file_path}")

        # Separate stems using mashup_engine
        from mashup_engine import MashupEngine
        engine = MashupEngine()

        # Get BPM and key
        logging.info("Analyzing BPM...")
        bpm, _ = engine.analyze_track(str(file_path))
        logging.info("Analyzing Key...")
        key = engine.analyze_key(str(file_path))
        key_name = engine._key_to_note(key) if key >= 0 else "Unknown"

        # Separate stems
        logging.info("Separating stems...")
        stem_dict = engine.separate_stems([str(file_path)])[0]

        # Copy stems to a simple location for serving
        serve_dir = audio_dir / 'stems'
        serve_dir.mkdir(exist_ok=True)

        # Use timestamp to avoid conflicts
        timestamp = str(int(time.time() * 1000))
        session_dir = serve_dir / timestamp
        session_dir.mkdir(exist_ok=True)

        stems = {}
        for stem_name, stem_path in stem_dict.items():
            if Path(stem_path).exists():
                # Copy to serve directory
                dest_path = session_dir / f"{stem_name}.wav"
                shutil.copy2(stem_path, str(dest_path))
                stems[stem_name] = f"/api/audio/{timestamp}/{stem_name}.wav"
                logging.info(f"✅ Copied {stem_name} to {dest_path}")
            else:
                logging.error(f"❌ Stem file not found: {stem_path}")

        if not stems:
            raise Exception("No stems were separated successfully")

        return jsonify({
            'stems': stems,
            'bpm': round(bpm, 1),
            'key': key_name,
            'filename': file.filename
        })
    except Exception as e:
        logging.error(f"Stem separation failed: {e}", exc_info=True)
        return jsonify({'error': f'Separation failed: {str(e)}'}), 500


@app.route('/api/audio/<path:filepath>')
def serve_audio(filepath):
    """Serve audio files"""
    audio_dir = BASE_DIR / 'Audio' / 'stems'
    file_path = audio_dir / filepath

    logging.info(f"[Audio] Requested: {filepath}")
    logging.info(f"[Audio] Looking in: {audio_dir}")
    logging.info(f"[Audio] Full path: {file_path}")
    logging.info(f"[Audio] Exists: {file_path.exists()}")

    if file_path.exists():
        logging.info(f"✅ Serving: {filepath}")
        return send_from_directory(str(audio_dir), filepath, mimetype='audio/wav')

    logging.error(f"❌ Not found: {file_path}")
    return jsonify({'error': 'File not found'}), 404


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


# ===== Audio Stats =====
@app.route('/api/audio-stats', methods=['GET'])
def get_audio_stats():
    """Get audio files count and total size"""
    try:
        audio_dir = BASE_DIR / 'Audio'
        if not audio_dir.exists():
            return jsonify({'file_count': 0, 'total_size_mb': 0, 'total_size_formatted': '0 MB'})

        file_count = 0
        total_size = 0

        for file_path in audio_dir.rglob('*'):
            if file_path.is_file():
                file_count += 1
                total_size += file_path.stat().st_size

        total_size_mb = total_size / (1024 * 1024)
        total_size_formatted = f"{total_size_mb:.1f} MB" if total_size_mb >= 1 else f"{total_size / 1024:.1f} KB"

        return jsonify({
            'file_count': file_count,
            'total_size_mb': round(total_size_mb, 2),
            'total_size_formatted': total_size_formatted
        })
    except Exception as e:
        logging.error(f"Stats error: {e}", exc_info=True)
        return jsonify({'file_count': 0, 'total_size_mb': 0, 'total_size_formatted': '0 MB'})


# ===== Cleanup =====
@app.route('/api/cleanup', methods=['POST'])
def cleanup_audio():
    """Clean up all generated audio files"""
    try:
        import shutil
        audio_dir = BASE_DIR / 'Audio'

        if audio_dir.exists():
            shutil.rmtree(str(audio_dir))
            audio_dir.mkdir(exist_ok=True)
            logging.info("✅ Cleaned up all audio files")
            return jsonify({'status': 'success', 'message': 'All audio files cleaned up'})
        else:
            return jsonify({'status': 'success', 'message': 'No audio files to clean'})
    except Exception as e:
        logging.error(f"Cleanup failed: {e}", exc_info=True)
        return jsonify({'error': f'Cleanup failed: {str(e)}'}), 500


# ===== Health Check =====
@app.route('/api/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
