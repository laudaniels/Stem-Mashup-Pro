"""Flask API for Stem Mashup Pro"""
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from pathlib import Path
import json
import logging
import time
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
            'filename': file.filename,
            'timestamp': timestamp
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
@app.route('/api/process-stems', methods=['POST'])
def process_stems():
    """Combined beatmatch + transpose processing"""
    data = request.json
    try:
        source_bpm = data.get('source_bpm')
        target_bpm = data.get('target_bpm')
        source_key = data.get('source_key')
        target_key = data.get('target_key')
        timestamp = data.get('timestamp')

        if not timestamp:
            return jsonify({'error': 'Missing timestamp'}), 400

        stems_dir = BASE_DIR / 'Audio' / 'stems' / timestamp
        from mashup_engine import MashupEngine
        engine = MashupEngine()

        processed_stems = {}

        for stem in ['vocals', 'drums', 'bass', 'other']:
            stem_path = stems_dir / f"{stem}.wav"
            if not stem_path.exists():
                logging.warning(f"Stem not found: {stem_path}")
                continue

            # Use original or previously processed version
            current_path = stem_path
            output_path = stems_dir / f"{stem}_processed.wav"

            # Apply beatmatch if needed
            if source_bpm and target_bpm and source_bpm != target_bpm:
                tempo_ratio = target_bpm / source_bpm
                if 0.5 <= tempo_ratio <= 2.0:
                    temp_path = stems_dir / f"{stem}_tempo.wav"
                    if engine.time_stretch_audio(str(current_path), str(temp_path), tempo_ratio):
                        current_path = temp_path
                        logging.info(f"✅ Beatmatched {stem}")

            # Apply transpose if needed
            if source_key and target_key and source_key != target_key:
                keys = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
                source_idx = keys.index(source_key) if source_key in keys else -1
                target_idx = keys.index(target_key) if target_key in keys else -1

                if source_idx >= 0 and target_idx >= 0:
                    semitones = target_idx - source_idx
                    if semitones > 6:
                        semitones -= 12
                    if semitones < -6:
                        semitones += 12

                    if engine.pitch_shift_audio(str(current_path), str(output_path), semitones):
                        processed_stems[stem] = f"/api/audio/{timestamp}/{stem}_processed.wav"
                        logging.info(f"✅ Processed {stem} (BPM: {source_bpm}→{target_bpm}, Key: {source_key}→{target_key})")
                    else:
                        processed_stems[stem] = f"/api/audio/{timestamp}/{stem}"
                else:
                    processed_stems[stem] = f"/api/audio/{timestamp}/{stem}"
            else:
                # Only beatmatch, no transpose needed
                if current_path != stem_path:
                    import shutil
                    shutil.copy2(str(current_path), str(output_path))
                    processed_stems[stem] = f"/api/audio/{timestamp}/{stem}_processed.wav"
                else:
                    processed_stems[stem] = f"/api/audio/{timestamp}/{stem}"

        if not processed_stems:
            return jsonify({'error': 'Processing failed'}), 500

        return jsonify({
            'status': 'success',
            'processed_stems': processed_stems
        })
    except Exception as e:
        logging.error(f"Process error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/beatmatch-stems', methods=['POST'])
def beatmatch_stems():
    """Time-stretch stems to target BPM"""
    data = request.json
    try:
        source_bpm = data.get('source_bpm')
        target_bpm = data.get('target_bpm')
        timestamp = data.get('timestamp')

        if not all([source_bpm, target_bpm, timestamp]):
            return jsonify({'error': 'Missing parameters'}), 400

        if source_bpm == target_bpm:
            return jsonify({'status': 'no_beatmatch', 'ratio': 1.0})

        # Calculate tempo ratio
        tempo_ratio = target_bpm / source_bpm
        if tempo_ratio < 0.5 or tempo_ratio > 2.0:
            return jsonify({'error': f'Tempo ratio {tempo_ratio:.2f} out of range (0.5-2.0)'}), 400

        # Time-stretch all stems
        stems_dir = BASE_DIR / 'Audio' / 'stems' / timestamp
        from mashup_engine import MashupEngine
        engine = MashupEngine()

        beatmatched_stems = {}
        for stem in ['vocals', 'drums', 'bass', 'other']:
            stem_path = stems_dir / f"{stem}.wav"
            if not stem_path.exists():
                logging.warning(f"Stem not found: {stem_path}")
                continue

            beatmatched_path = stems_dir / f"{stem}_beatmatched.wav"
            if engine.time_stretch_audio(str(stem_path), str(beatmatched_path), tempo_ratio):
                beatmatched_stems[stem] = f"/api/audio/{timestamp}/{stem}_beatmatched.wav"
                logging.info(f"✅ Beatmatched {stem} from {source_bpm} to {target_bpm} BPM (ratio: {tempo_ratio:.2f})")
            else:
                logging.error(f"❌ Failed to beatmatch {stem}")

        if not beatmatched_stems:
            return jsonify({'error': 'Beatmatching failed'}), 500

        return jsonify({
            'status': 'success',
            'source_bpm': source_bpm,
            'target_bpm': target_bpm,
            'ratio': tempo_ratio,
            'beatmatched_stems': beatmatched_stems
        })
    except Exception as e:
        logging.error(f"Beatmatch error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/transpose-stems', methods=['POST'])
def transpose_stems():
    """Transpose stems to a target key"""
    data = request.json
    try:
        source_key = data.get('source_key')
        target_key = data.get('target_key')
        timestamp = data.get('timestamp')

        if not all([source_key, target_key, timestamp]):
            return jsonify({'error': 'Missing parameters'}), 400

        # Calculate semitone shift
        keys = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        source_idx = keys.index(source_key) if source_key in keys else -1
        target_idx = keys.index(target_key) if target_key in keys else -1

        if source_idx == -1 or target_idx == -1:
            return jsonify({'error': 'Invalid key'}), 400

        semitones = target_idx - source_idx
        if semitones > 6:
            semitones -= 12
        if semitones < -6:
            semitones += 12

        if semitones == 0:
            # No transposition needed
            return jsonify({'status': 'no_transposition', 'semitones': 0})

        # Transpose all stems
        stems_dir = BASE_DIR / 'Audio' / 'stems' / timestamp
        from mashup_engine import MashupEngine
        engine = MashupEngine()

        transposed_stems = {}
        for stem in ['vocals', 'drums', 'bass', 'other']:
            stem_path = stems_dir / f"{stem}.wav"
            if not stem_path.exists():
                logging.warning(f"Stem not found: {stem_path}")
                continue

            transposed_path = stems_dir / f"{stem}_transposed.wav"
            if engine.pitch_shift_audio(str(stem_path), str(transposed_path), semitones):
                transposed_stems[stem] = f"/api/audio/{timestamp}/{stem}_transposed.wav"
                logging.info(f"✅ Transposed {stem} by {semitones} semitones")
            else:
                logging.error(f"❌ Failed to transpose {stem}")

        if not transposed_stems:
            return jsonify({'error': 'Transposition failed'}), 500

        return jsonify({
            'status': 'success',
            'semitones': semitones,
            'transposed_stems': transposed_stems
        })
    except Exception as e:
        logging.error(f"Transpose error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/render-final-mix', methods=['POST'])
def render_final_mix():
    """Render final mixed WAV from stems with current volumes"""
    data = request.json
    try:
        import subprocess
        import tempfile
        from pathlib import Path

        timestamps = data.get('timestamps')  # [timestamp_slot0, timestamp_slot1]
        volumes = data.get('volumes')  # {0: {stem: vol}, 1: {stem: vol}}
        crossfader = data.get('crossfader', 50) / 100.0

        if not timestamps or not volumes:
            return jsonify({'error': 'Missing parameters'}), 400

        # Create output file
        output_dir = BASE_DIR / 'Audio' / 'renders'
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / f"final_mix_{int(time.time() * 1000)}.wav"

        # Build FFmpeg command to mix stems
        inputs = []
        filters = []
        input_idx = 0

        for slot in range(2):
            if not timestamps[slot]:
                continue

            stems_dir = BASE_DIR / 'Audio' / 'stems' / timestamps[slot]
            slot_volume = (1 - crossfader) if slot == 0 else crossfader

            for stem in ['vocals', 'drums', 'bass', 'other']:
                # Try processed version first, then original
                stem_file = stems_dir / f"{stem}_processed.wav"
                if not stem_file.exists():
                    stem_file = stems_dir / f"{stem}.wav"

                if stem_file.exists():
                    inputs.append('-i')
                    inputs.append(str(stem_file))

                    stem_volume = volumes.get(slot, {}).get(stem, 1.0)
                    master_volume = slot_volume * stem_volume

                    filters.append(f"[{input_idx}]volume={master_volume}[s{input_idx}]")
                    input_idx += 1

        if input_idx == 0:
            return jsonify({'error': 'No stems found'}), 400

        # Concat all volumes
        concat_str = ''.join([f'[s{i}]' for i in range(input_idx)])
        filter_complex = ';'.join(filters) + f';{concat_str}amix=inputs={input_idx}[out]'

        cmd = ['ffmpeg', '-y'] + inputs + [
            '-filter_complex', filter_complex,
            '-map', '[out]',
            '-acodec', 'pcm_s16le',
            str(output_file)
        ]

        logging.info(f"Rendering mix with {input_idx} stems...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode == 0 and output_file.exists():
            logging.info(f"✅ Mix rendered: {output_file}")
            return jsonify({
                'status': 'success',
                'file': f'/api/download-file/{output_file.name}',
                'size_mb': round(output_file.stat().st_size / (1024 * 1024), 2)
            })
        else:
            logging.error(f"FFmpeg error: {result.stderr}")
            return jsonify({'error': 'Rendering failed'}), 500

    except Exception as e:
        logging.error(f"Render error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/download-stems-zip', methods=['POST'])
def download_stems_zip():
    """Download all stems as ZIP"""
    data = request.json
    try:
        import zipfile
        import io

        timestamps = data.get('timestamps')
        include_original = data.get('include_original', True)
        include_processed = data.get('include_processed', True)

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for slot, timestamp in enumerate(timestamps):
                if not timestamp:
                    continue

                stems_dir = BASE_DIR / 'Audio' / 'stems' / timestamp
                song_name = f"Song_{slot + 1}"

                # Add original stems
                if include_original:
                    for stem in ['vocals', 'drums', 'bass', 'other']:
                        stem_file = stems_dir / f"{stem}.wav"
                        if stem_file.exists():
                            arcname = f"{song_name}/original/{stem}.wav"
                            zip_file.write(str(stem_file), arcname)

                # Add processed stems
                if include_processed:
                    for stem in ['vocals', 'drums', 'bass', 'other']:
                        stem_file = stems_dir / f"{stem}_processed.wav"
                        if stem_file.exists():
                            arcname = f"{song_name}/processed/{stem}.wav"
                            zip_file.write(str(stem_file), arcname)

        zip_buffer.seek(0)
        timestamp_str = int(time.time() * 1000)
        zip_path = BASE_DIR / 'Audio' / f'stems_{timestamp_str}.zip'

        with open(zip_path, 'wb') as f:
            f.write(zip_buffer.getvalue())

        logging.info(f"✅ ZIP created: {zip_path}")
        return jsonify({
            'status': 'success',
            'file': f'/api/download-file/{zip_path.name}',
            'size_mb': round(zip_path.stat().st_size / (1024 * 1024), 2)
        })

    except Exception as e:
        logging.error(f"ZIP error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/download-file/<filename>')
def download_file(filename):
    """Download a file"""
    try:
        from pathlib import Path

        # Security: only allow files from specific directories
        safe_dirs = [
            BASE_DIR / 'Audio' / 'stems',
            BASE_DIR / 'Audio' / 'renders',
            BASE_DIR / 'Audio'
        ]

        file_path = None
        for safe_dir in safe_dirs:
            candidate = safe_dir / filename
            if candidate.exists() and candidate.is_file():
                file_path = candidate
                break

        if not file_path:
            return jsonify({'error': 'File not found'}), 404

        return send_file(str(file_path), as_attachment=True)

    except Exception as e:
        logging.error(f"Download error: {e}")
        return jsonify({'error': str(e)}), 500


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
