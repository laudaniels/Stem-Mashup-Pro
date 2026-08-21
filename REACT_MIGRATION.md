# React + Flask Migration Guide

## Architecture

```
Backend (Flask API) → Audio Engine → Loop Buffer
         ↓
React Frontend (Vite) → HTML5 Audio Player
```

## Setup

### 1. Install Frontend Dependencies

```bash
cd frontend
npm install
```

### 2. Install Flask Dependencies

```bash
pip install flask flask-cors
```

### 3. Build Frontend for Production

```bash
cd frontend
npm run build
```

This creates `frontend/dist/` with optimized static files.

## Development

### Terminal 1: React Frontend (Dev Server)
```bash
cd frontend
npm run dev
```
Runs on http://localhost:3000 with hot reloading.
Proxy to Flask on /api routes.

### Terminal 2: Flask Backend
```bash
python api.py
```
Runs on http://127.0.0.1:5000
- Serves React frontend
- Provides /api/* endpoints
- Handles audio processing

## API Endpoints

### Song Management
- `POST /api/load-song/<slot>` - Load audio file
- `GET /api/status` - Get app status

### Loop Control
- `POST /api/start-loop` - Start loop with settings
- `POST /api/stop-loop` - Stop loop playback

### Rendering
- `POST /api/render` - Render final mix

### Health
- `GET /api/health` - Health check

## Key Improvements Over Gradio

1. **Direct HTML5 Audio Control**
   - No SSRF issues
   - Proper loop attribute support
   - Full audio element access

2. **Real-Time Updates**
   - File change detection every 1 second
   - Seamless audio reload
   - No full page refreshes

3. **Custom UI**
   - Tailwind CSS styling
   - Responsive layout
   - Professional audio app UX

4. **Better Performance**
   - Lightweight Vite bundler
   - No Gradio overhead
   - Fast hot reloading in dev

## Directory Structure

```
stem-mashup-pro/
├── api.py                      # Flask API server
├── gradio_app.py              # Existing audio engine (reused)
├── mashup_engine.py           # Core mixer logic
├── loop_render_buffer.py      # Loop management
├── audio_server.py            # Audio streaming
├── frontend/                  # React app
│   ├── src/
│   │   ├── components/        # React components
│   │   ├── styles/           # CSS
│   │   ├── App.jsx           # Main app
│   │   └── main.jsx          # Entry point
│   ├── index.html            # HTML template
│   ├── vite.config.js        # Vite config
│   ├── package.json          # Dependencies
│   └── dist/                 # Built frontend (production)
└── REACT_MIGRATION.md        # This file
```

## Next Steps

1. ✅ Frontend structure created
2. ✅ API endpoints defined
3. 🔄 Install deps and test:
   ```bash
   cd frontend && npm install
   npm run build
   cd ..
   python api.py
   ```
4. Visit http://127.0.0.1:5000

## Troubleshooting

**CORS errors?**
- Flask CORS is enabled
- Check origin in browser console

**Audio not playing?**
- Check Flask is running on 5000
- Check audio file path is correct
- Browser may block autoplay - click play button

**Sliders not updating loop?**
- Loop file check runs every 1 second
- Should see "[Loop] File changed" in console
- Check /api/start-loop endpoint returns file path

**Hot reload not working in dev?**
- Make sure `npm run dev` is running
- Check vite.config.js proxy settings
- Clear browser cache if needed
