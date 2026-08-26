import React, { useState, useRef, useEffect } from 'react';
import StemLoader from './StemLoader';
import '../styles/DualMixer.css';

export default function DualMixer() {
  const [songs, setSongs] = useState([null, null]);
  const [stems, setStems] = useState([null, null]);
  const [metadata, setMetadata] = useState([null, null]);
  const [loading, setLoading] = useState([false, false]);
  const [error, setError] = useState('');
  const [playing, setPlaying] = useState(false);
  const [editingBpm, setEditingBpm] = useState([false, false]);
  const [editingKey, setEditingKey] = useState([false, false]);
  const [overrideBpm, setOverrideBpm] = useState([null, null]);
  const [overrideKey, setOverrideKey] = useState([null, null]);
  const [targetKey, setTargetKey] = useState(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [audioStats, setAudioStats] = useState({ file_count: 0, total_size_formatted: '0 MB' });

  // Audio refs for each song's stems
  const audioRefsRef = useRef({
    0: { vocals: useRef(null), drums: useRef(null), bass: useRef(null), other: useRef(null) },
    1: { vocals: useRef(null), drums: useRef(null), bass: useRef(null), other: useRef(null) }
  });

  // Volume states for each song
  const [volumes, setVolumes] = useState({
    0: { vocals: 1.0, drums: 1.0, bass: 1.0, other: 1.0 },
    1: { vocals: 1.0, drums: 1.0, bass: 1.0, other: 1.0 }
  });

  // Crossfader: 0 = song1 only, 50 = both, 100 = song2 only
  const [crossfader, setCrossfader] = useState(50);

  // Fetch audio stats
  const fetchStats = async () => {
    try {
      const response = await fetch('/api/audio-stats');
      const data = await response.json();
      setAudioStats(data);
    } catch (err) {
      console.error('Stats fetch error:', err);
    }
  };

  // Fetch stats on component mount
  React.useEffect(() => {
    fetchStats();
  }, []);

  // Handle stem upload for a song slot
  const handleStemsLoaded = async (file, slot) => {
    const newLoading = [...loading];
    newLoading[slot] = true;
    setLoading(newLoading);
    setError('');

    // Show filename immediately while processing
    const newMetadata = [...metadata];
    newMetadata[slot] = { filename: file.name };
    setMetadata(newMetadata);

    console.log(`📥 Song ${slot + 1} upload started`);

    try {
      const formData = new FormData();
      formData.append('file', file);

      console.log(`🔄 Uploading Song ${slot + 1} for stem separation...`);
      const response = await fetch('/api/separate-stems', {
        method: 'POST',
        body: formData
      });

      if (!response.ok) throw new Error(`Server error: ${response.status}`);

      const data = await response.json();
      console.log(`✅ Song ${slot + 1} stems:`, data);

      setStems(prevStems => {
        const newStems = [...prevStems];
        newStems[slot] = data.stems;
        console.log(`✅ Song ${slot + 1} stems loaded. State:`, { stems: newStems, song1: !!newStems[0], song2: !!newStems[1] });
        return newStems;
      });

      setMetadata(prevMetadata => {
        const newMetadata = [...prevMetadata];
        newMetadata[slot] = data;
        return newMetadata;
      });

      // Set audio sources
      Object.entries(data.stems).forEach(([stemName, url]) => {
        if (audioRefsRef.current[slot][stemName]?.current) {
          audioRefsRef.current[slot][stemName].current.src = url;
          audioRefsRef.current[slot][stemName].current.load();
        }
      });

      // Refresh stats
      fetchStats();
    } catch (err) {
      console.error(`❌ Error:`, err);
      setError(`Error loading Song ${slot + 1}: ${err.message}`);
    } finally {
      setLoading(prevLoading => {
        const updated = [...prevLoading];
        updated[slot] = false;
        return updated;
      });
    }
  };

  // Play/pause both songs
  const togglePlayback = () => {
    const stemNames = ['vocals', 'drums', 'bass', 'other'];

    if (playing) {
      // Stop all
      [0, 1].forEach(slot => {
        stemNames.forEach(stem => {
          if (audioRefsRef.current[slot][stem]?.current) {
            audioRefsRef.current[slot][stem].current.pause();
            audioRefsRef.current[slot][stem].current.currentTime = 0;
          }
        });
      });
      setPlaying(false);
      setCurrentTime(0);
    } else {
      // Play all loaded stems
      const crossfadePercent = crossfader / 100;
      const song1Volume = 1 - crossfadePercent; // 1 at 0%, 0 at 100%
      const song2Volume = crossfadePercent; // 0 at 0%, 1 at 100%

      [0, 1].forEach(slot => {
        stemNames.forEach(stem => {
          const audioEl = audioRefsRef.current[slot][stem]?.current;
          if (audioEl && audioEl.src) {
            // Apply crossfader
            const masterVol = slot === 0 ? song1Volume : song2Volume;
            const stemVol = volumes[slot]?.[stem] ?? 1.0;
            audioEl.volume = masterVol * stemVol;
            audioEl.play().catch(e => console.error(`Play error (Song ${slot + 1} ${stem}):`, e));
          }
        });
      });
      setPlaying(true);
    }
  };

  // Update volume
  const handleVolumeChange = (slot, stem, value) => {
    setVolumes(prev => ({
      ...prev,
      [slot]: { ...prev[slot], [stem]: value }
    }));

    if (playing && audioRefsRef.current[slot][stem]?.current) {
      const crossfadePercent = crossfader / 100;
      const masterVol = slot === 0 ? (1 - crossfadePercent) : crossfadePercent;
      audioRefsRef.current[slot][stem].current.volume = masterVol * value;
    }
  };

  // Update crossfader
  const handleCrossfaderChange = (value) => {
    setCrossfader(value);

    if (playing) {
      const crossfadePercent = value / 100;
      const song1Volume = 1 - crossfadePercent;
      const song2Volume = crossfadePercent;
      const stemNames = ['vocals', 'drums', 'bass', 'other'];

      [0, 1].forEach(slot => {
        stemNames.forEach(stem => {
          const audioEl = audioRefsRef.current[slot][stem]?.current;
          if (audioEl) {
            const masterVol = slot === 0 ? song1Volume : song2Volume;
            const stemVol = volumes[slot]?.[stem] ?? 1.0;
            audioEl.volume = masterVol * stemVol;
          }
        });
      });
    }
  };

  // Track progress
  useEffect(() => {
    if (!playing) return;

    const interval = setInterval(() => {
      if (audioRefsRef.current[0].vocals?.current) {
        const ct = audioRefsRef.current[0].vocals.current.currentTime;
        const dur = audioRefsRef.current[0].vocals.current.duration || 0;
        setCurrentTime(ct);
        setDuration(dur);

        if (ct >= dur - 0.1) {
          setPlaying(false);
          setCurrentTime(0);
          [0, 1].forEach(slot => {
            ['vocals', 'drums', 'bass', 'other'].forEach(stem => {
              if (audioRefsRef.current[slot][stem]?.current) {
                audioRefsRef.current[slot][stem].current.pause();
                audioRefsRef.current[slot][stem].current.currentTime = 0;
              }
            });
          });
        }
      }
    }, 100);

    return () => clearInterval(interval);
  }, [playing]);

  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

  const getEffectiveBpm = (slot) => overrideBpm[slot] !== null ? overrideBpm[slot] : metadata[slot]?.bpm;
  const getEffectiveKey = (slot) => overrideKey[slot] !== null ? overrideKey[slot] : metadata[slot]?.key;

  const getSemitoneShift = (fromKey, toKey) => {
    const keyToIndex = { C: 0, 'C#': 1, D: 2, 'D#': 3, E: 4, F: 5, 'F#': 6, G: 7, 'G#': 8, A: 9, 'A#': 10, B: 11 };
    const from = keyToIndex[fromKey];
    const to = keyToIndex[toKey];
    if (from === undefined || to === undefined) return 0;
    let diff = to - from;
    if (diff > 6) diff -= 12;
    if (diff < -6) diff += 12;
    return diff;
  };

  const handleBpmOverride = (slot, value) => {
    const newOverride = [...overrideBpm];
    newOverride[slot] = value ? parseFloat(value) : null;
    setOverrideBpm(newOverride);
  };

  const handleKeyOverride = (slot, value) => {
    const newOverride = [...overrideKey];
    newOverride[slot] = value || null;
    setOverrideKey(newOverride);
  };

  // Cleanup all audio files
  const handleCleanup = async () => {
    if (!confirm('🗑️ Delete all generated audio files? This cannot be undone.')) return;

    try {
      const response = await fetch('/api/cleanup', { method: 'POST' });
      const data = await response.json();

      if (response.ok) {
        alert('✅ Cleanup complete! All audio files deleted.');
        // Reset state
        setSongs([null, null]);
        setStems([null, null]);
        setMetadata([null, null]);
        setLoading([false, false]);
        setPlaying(false);
        setCurrentTime(0);
        setDuration(0);
        setCrossfader(50);
        setAudioStats({ file_count: 0, total_size_formatted: '0 MB' });
      } else {
        alert(`❌ Cleanup failed: ${data.error}`);
      }
    } catch (err) {
      console.error('Cleanup error:', err);
      alert(`❌ Error: ${err.message}`);
    }
  };

  // Render mixer for one song
  const renderSongMixer = (slot) => {
    const songName = metadata[slot]?.filename?.replace(/\.[^/.]+$/, '') || `Song ${slot + 1}`;

    return (
    <div className="song-mixer">
      <h3>{songName}</h3>

      {metadata[slot] && (
        <div className="metadata">
          <p><strong>{metadata[slot].filename}</strong></p>
          {stems[slot] && (
          <div style={{ marginTop: '10px', display: 'flex', gap: '20px', fontSize: '13px' }}>
            {/* BPM Override */}
            <div style={{ flex: 1 }}>
              <label style={{ color: '#999', fontSize: '11px' }}>BPM</label>
              {editingBpm[slot] ? (
                <div style={{ display: 'flex', gap: '5px', marginTop: '5px' }}>
                  <input
                    type="number"
                    value={overrideBpm[slot] !== null ? overrideBpm[slot] : metadata[slot].bpm}
                    onChange={(e) => handleBpmOverride(slot, e.target.value)}
                    style={{
                      flex: 1,
                      background: 'rgba(99, 102, 241, 0.2)',
                      border: '1px solid #6366f1',
                      color: '#fff',
                      padding: '4px 8px',
                      borderRadius: '4px',
                      fontSize: '12px'
                    }}
                  />
                  <button
                    onClick={() => setEditingBpm(prev => { const n = [...prev]; n[slot] = false; return n; })}
                    style={{
                      background: '#6366f1',
                      color: '#fff',
                      border: 'none',
                      padding: '4px 8px',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      fontSize: '11px'
                    }}
                  >
                    ✓
                  </button>
                </div>
              ) : (
                <div style={{ display: 'flex', gap: '5px', marginTop: '5px', alignItems: 'center' }}>
                  <span style={{ color: overrideBpm[slot] !== null ? '#8b5cf6' : '#ccc' }}>
                    {getEffectiveBpm(slot)} {overrideBpm[slot] !== null ? '(custom)' : '(detected)'}
                  </span>
                  <button
                    onClick={() => setEditingBpm(prev => { const n = [...prev]; n[slot] = true; return n; })}
                    style={{
                      background: 'transparent',
                      color: '#6366f1',
                      border: '1px solid #6366f1',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      fontSize: '10px'
                    }}
                  >
                    ✎
                  </button>
                </div>
              )}
            </div>

            {/* Key Override */}
            <div style={{ flex: 1 }}>
              <label style={{ color: '#999', fontSize: '11px' }}>KEY</label>
              {editingKey[slot] ? (
                <div style={{ display: 'flex', gap: '5px', marginTop: '5px' }}>
                  <select
                    value={overrideKey[slot] !== null ? overrideKey[slot] : metadata[slot].key}
                    onChange={(e) => handleKeyOverride(slot, e.target.value)}
                    style={{
                      flex: 1,
                      background: 'rgba(99, 102, 241, 0.2)',
                      border: '1px solid #6366f1',
                      color: '#fff',
                      padding: '4px 8px',
                      borderRadius: '4px',
                      fontSize: '12px'
                    }}
                  >
                    <option value="">Clear override</option>
                    {KEYS.map(k => <option key={k} value={k}>{k}</option>)}
                  </select>
                  <button
                    onClick={() => setEditingKey(prev => { const n = [...prev]; n[slot] = false; return n; })}
                    style={{
                      background: '#6366f1',
                      color: '#fff',
                      border: 'none',
                      padding: '4px 8px',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      fontSize: '11px'
                    }}
                  >
                    ✓
                  </button>
                </div>
              ) : (
                <div style={{ display: 'flex', gap: '5px', marginTop: '5px', alignItems: 'center' }}>
                  <span style={{ color: overrideKey[slot] !== null ? '#8b5cf6' : '#ccc' }}>
                    {getEffectiveKey(slot)} {overrideKey[slot] !== null ? '(custom)' : '(detected)'}
                  </span>
                  <button
                    onClick={() => setEditingKey(prev => { const n = [...prev]; n[slot] = true; return n; })}
                    style={{
                      background: 'transparent',
                      color: '#6366f1',
                      border: '1px solid #6366f1',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      fontSize: '10px'
                    }}
                  >
                    ✎
                  </button>
                </div>
              )}
            </div>
          </div>
          )}
        </div>
      )}

      {!stems[slot] ? (
        <StemLoader
          onStemsLoaded={(file) => handleStemsLoaded(file, slot)}
          loading={loading[slot]}
        />
      ) : (
        <div className="stem-controls">
          <h4>🎚️ Volumes</h4>
          {['vocals', 'drums', 'bass', 'other'].map(stem => (
            <div key={stem} className="volume-control">
              <label>{stem.toUpperCase()}</label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={volumes[slot]?.[stem] ?? 1.0}
                onChange={(e) => handleVolumeChange(slot, stem, parseFloat(e.target.value))}
                className="slider"
              />
              <span className="volume-value">
                {Math.round((volumes[slot]?.[stem] ?? 1.0) * 100)}%
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Hidden audio elements */}
      <div style={{ display: 'none' }}>
        {['vocals', 'drums', 'bass', 'other'].map(stem => (
          <audio
            key={stem}
            ref={audioRefsRef.current[slot][stem]}
            crossOrigin="anonymous"
            onError={(e) => console.error(`Song ${slot + 1} ${stem} error:`, e)}
          />
        ))}
      </div>
    </div>
    );
  };

  return (
    <div className="dual-mixer">
      {error && (
        <div className="error-banner">
          {error}
        </div>
      )}

      <div className="mixer-container">
        {/* Two song mixers side by side */}
        <div className="songs-row">
          {renderSongMixer(0)}
          {renderSongMixer(1)}
        </div>

        {/* Playback & Crossfader Controls */}
        {stems[0] && stems[1] ? (
          <div className="playback-section">
            <div className="playback-controls">
              <button onClick={togglePlayback} className="play-btn">
                {playing ? '⏸ PAUSE' : '▶ PLAY BOTH'}
              </button>

              <div className="progress-bar">
                <div
                  className="progress-fill"
                  style={{ width: `${duration > 0 ? (currentTime / duration) * 100 : 0}%` }}
                ></div>
              </div>

              <span className="time-display">
                {formatTime(currentTime)} / {formatTime(duration)}
              </span>
            </div>

            {/* Crossfader */}
            <div className="crossfader-section">
              <label>🎛️ Crossfader</label>
              <div className="crossfader-labels">
                <span>Song 1</span>
                <span>Both</span>
                <span>Song 2</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                step="1"
                value={crossfader}
                onChange={(e) => handleCrossfaderChange(parseFloat(e.target.value))}
                className="crossfader-slider"
              />
              <div className="crossfader-value">
                {crossfader === 50 ? 'Both: 50/50' : crossfader < 50 ? `Song 1: ${100 - crossfader}%` : `Song 2: ${crossfader}%`}
              </div>
            </div>
          </div>
        ) : null}

        {/* Key Transposition */}
        {stems[0] || stems[1] ? (
          <div style={{
            background: 'rgba(99, 102, 241, 0.05)',
            border: '1px solid rgba(99, 102, 241, 0.2)',
            padding: '20px',
            borderRadius: '12px',
            marginTop: '20px'
          }}>
            <label style={{ display: 'block', fontSize: '14px', fontWeight: 'bold', color: '#ccc', marginBottom: '10px' }}>
              🎼 Target Key (for transposition)
            </label>
            <div style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
              <select
                value={targetKey || ''}
                onChange={(e) => setTargetKey(e.target.value || null)}
                style={{
                  flex: 1,
                  padding: '8px',
                  background: 'rgba(99, 102, 241, 0.2)',
                  border: '1px solid #6366f1',
                  color: '#fff',
                  borderRadius: '6px',
                  fontSize: '14px'
                }}
              >
                <option value="">No transposition</option>
                {KEYS.map(k => <option key={k} value={k}>{k}</option>)}
              </select>
            </div>

            {/* Advisory */}
            {targetKey && (stems[0] || stems[1]) && (
              <div style={{
                background: 'rgba(139, 92, 246, 0.1)',
                border: '1px solid rgba(139, 92, 246, 0.3)',
                padding: '15px',
                borderRadius: '8px',
                fontSize: '13px'
              }}>
                <p style={{ margin: '0 0 10px 0', color: '#ddd', fontWeight: 'bold' }}>📍 Transposition Advisory:</p>
                <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
                  {[0, 1].map(slot => {
                    const sourceKey = getEffectiveKey(slot);
                    if (!sourceKey || !stems[slot]) return null;
                    const semitones = getSemitoneShift(sourceKey, targetKey);
                    const direction = semitones > 0 ? '↑' : semitones < 0 ? '↓' : '=';
                    const absSteps = Math.abs(semitones);
                    return (
                      <div key={slot} style={{ color: '#aaa' }}>
                        <strong style={{ color: '#8b5cf6' }}>{metadata[slot]?.filename?.replace(/\.[^/.]+$/, '')}</strong>
                        <br />
                        {sourceKey} → {targetKey} <span style={{ color: '#a78bfa', fontSize: '16px' }}>{direction}</span> {absSteps} semitone{absSteps !== 1 ? 's' : ''}
                      </div>
                    );
                  })}
                </div>
                <p style={{ margin: '10px 0 0 0', color: '#999', fontSize: '12px' }}>
                  ⚠️ Note: Transposition requires pitch-shifting. This is a preview - actual audio processing coming soon.
                </p>
              </div>
            )}
          </div>
        ) : null}

        {/* Audio Stats & Cleanup */}
        <div style={{
          marginTop: '40px',
          paddingTop: '20px',
          borderTop: '1px solid rgba(99, 102, 241, 0.2)',
          textAlign: 'center'
        }}>
          <div style={{
            marginBottom: '15px',
            fontSize: '13px',
            color: '#aaa'
          }}>
            <strong>💾 Generated Files:</strong> {audioStats.file_count} files ({audioStats.total_size_formatted})
          </div>

          <button
            onClick={handleCleanup}
            style={{
              background: 'rgba(239, 68, 68, 0.2)',
              color: '#fca5a5',
              border: '1px solid #ef4444',
              padding: '10px 20px',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: 'bold',
              transition: 'all 0.2s'
            }}
            onMouseEnter={(e) => e.target.style.background = 'rgba(239, 68, 68, 0.3)'}
            onMouseLeave={(e) => e.target.style.background = 'rgba(239, 68, 68, 0.2)'}
          >
            🗑️ Cleanup Audio Files
          </button>
        </div>
      </div>
    </div>
  );
}
