import { useState, useEffect } from 'react'
import SongLoader from './components/SongLoader'
import Mixer from './components/Mixer'
import LoopPlayer from './components/LoopPlayer'
import Status from './components/Status'

export default function App() {
  const [songs, setSongs] = useState([null, null])
  const [stems, setStems] = useState([null, null])
  const [status, setStatus] = useState('')
  const [loopFile, setLoopFile] = useState(null)
  const [sliders, setSliders] = useState({
    s0_vocals_vol: 1, s0_beats_vol: 1, s0_bass_vol: 1, s0_other_vol: 1,
    s0_pitch_shift: 0, s0_reverb: 0, s0_speed: 1, s0_eq_low: 0, s0_eq_mid: 0, s0_eq_high: 0,
    s1_vocals_vol: 1, s1_beats_vol: 1, s1_bass_vol: 1, s1_other_vol: 1,
    s1_pitch_shift: 0, s1_reverb: 0, s1_speed: 1, s1_eq_low: 0, s1_eq_mid: 0, s1_eq_high: 0,
  })
  const [settings, setSettings] = useState({
    crossfader: 50,
    target_bpm: 0,
    beatmatch: false,
    loop_start: 0,
    loop_length: '8 bars (20s)',
  })

  return (
    <div className="app">
      <header className="app-header">
        <h1>🎵 Stem Mashup Pro</h1>
        <Status message={status} />
      </header>

      <main className="app-main">
        <div className="section">
          <h2>Load & Analyze</h2>
          <SongLoader onSongsLoaded={setSongs} onStemsReady={setStems} onStatus={setStatus} />
        </div>

        {stems[0] && stems[1] && (
          <>
            <div className="section">
              <h2>Mixer Controls</h2>
              <Mixer
                sliders={sliders}
                onSliderChange={setSliders}
                settings={settings}
                onSettingsChange={setSettings}
              />
            </div>

            <div className="section">
              <h2>Real-Time Loop</h2>
              <LoopPlayer
                sliders={sliders}
                settings={settings}
                loopFile={loopFile}
                onLoopReady={setLoopFile}
                onStatus={setStatus}
                onSettingsChange={setSettings}
              />
            </div>
          </>
        )}
      </main>
    </div>
  )
}
