const express = require('express');
const path = require('path');
const fs = require('fs');

function timestamp() {
  const d = new Date();
  const pad = (n, l = 2) => String(n).padStart(l, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

const app = express();
const PORT = parseInt(process.env.PORT || '3010');
const VOICEVOX_URL = process.env.VOICEVOX_URL || 'http://127.0.0.1:50021';
const OUTPUT_DIR = path.join(__dirname, 'outputs');

fs.mkdirSync(OUTPUT_DIR, { recursive: true });

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));
app.use('/outputs', express.static(OUTPUT_DIR));

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

app.get('/health', async (req, res) => {
  let vvReady = false;
  let vvVersion = null;
  try {
    const r = await fetch(`${VOICEVOX_URL}/version`);
    if (r.ok) {
      vvVersion = await r.text();
      vvReady = true;
    }
  } catch (_) {}
  res.json({ node: true, voicevox: vvReady, voicevox_version: vvVersion, voicevox_url: VOICEVOX_URL });
});

// ---------------------------------------------------------------------------
// Speakers proxy
// ---------------------------------------------------------------------------

app.get('/speakers', async (req, res) => {
  try {
    const r = await fetch(`${VOICEVOX_URL}/speakers`);
    if (!r.ok) { res.status(502).json({ error: 'VOICEVOX engine error' }); return; }
    res.json(await r.json());
  } catch (e) {
    res.status(503).json({ error: 'VOICEVOX engine is not running', detail: e.message });
  }
});

// speaker_info proxy (portrait + style icons)
app.get('/speaker-info', async (req, res) => {
  const { speaker_uuid } = req.query;
  if (!speaker_uuid) { res.status(400).json({ error: 'speaker_uuid is required' }); return; }
  try {
    const r = await fetch(`${VOICEVOX_URL}/speaker_info?speaker_uuid=${encodeURIComponent(speaker_uuid)}`);
    if (!r.ok) { res.status(502).json({ error: 'VOICEVOX engine error' }); return; }
    res.json(await r.json());
  } catch (e) {
    res.status(503).json({ error: 'VOICEVOX engine is not running', detail: e.message });
  }
});

// ---------------------------------------------------------------------------
// TTS (sync)
// ---------------------------------------------------------------------------

app.post('/tts', async (req, res) => {
  const {
    text, speaker,
    speedScale, pitchScale, intonationScale, volumeScale,
    outputSamplingRate, outputStereo,
  } = req.body || {};

  if (!text || !String(text).trim()) { res.status(400).json({ error: 'text is required' }); return; }
  if (speaker === undefined || speaker === null) { res.status(400).json({ error: 'speaker is required' }); return; }

  try {
    // Step 1: audio_query
    const queryRes = await fetch(
      `${VOICEVOX_URL}/audio_query?text=${encodeURIComponent(text)}&speaker=${speaker}`,
      { method: 'POST' }
    );
    if (!queryRes.ok) {
      const detail = await queryRes.text();
      res.status(502).json({ error: 'audio_query failed', detail });
      return;
    }
    const query = await queryRes.json();

    // Apply optional overrides
    if (speedScale      !== undefined) query.speedScale      = parseFloat(speedScale);
    if (pitchScale      !== undefined) query.pitchScale      = parseFloat(pitchScale);
    if (intonationScale !== undefined) query.intonationScale = parseFloat(intonationScale);
    if (volumeScale     !== undefined) query.volumeScale     = parseFloat(volumeScale);
    if (outputSamplingRate !== undefined) query.outputSamplingRate = parseInt(outputSamplingRate);
    if (outputStereo    !== undefined) query.outputStereo    = Boolean(outputStereo);

    // Step 2: synthesis
    const synthRes = await fetch(
      `${VOICEVOX_URL}/synthesis?speaker=${speaker}`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(query) }
    );
    if (!synthRes.ok) {
      const detail = await synthRes.text();
      res.status(502).json({ error: 'synthesis failed', detail });
      return;
    }

    const filename = `${timestamp()}.wav`;
    const outputPath = path.join(OUTPUT_DIR, filename);
    const buf = Buffer.from(await synthRes.arrayBuffer());
    fs.writeFileSync(outputPath, buf);

    res.json({
      message: 'ok',
      model: 'VOICEVOX',
      speaker,
      audioUrl: `/outputs/${filename}`,
    });
  } catch (e) {
    console.error('[VOICEVOX] tts error:', e.message);
    res.status(500).json({ error: e.message });
  }
});

// ---------------------------------------------------------------------------
// TTS (SSE stream)
// ---------------------------------------------------------------------------

app.post('/tts/stream', async (req, res) => {
  const {
    text, speaker,
    speedScale, pitchScale, intonationScale, volumeScale,
    outputSamplingRate, outputStereo,
  } = req.body || {};

  if (!text || !String(text).trim()) { res.status(400).json({ error: 'text is required' }); return; }
  if (speaker === undefined || speaker === null) { res.status(400).json({ error: 'speaker is required' }); return; }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('X-Accel-Buffering', 'no');

  const send = (obj) => res.write(`data: ${JSON.stringify(obj)}\n\n`);

  try {
    send({ type: 'progress', percent: 20, desc: 'テキスト解析中 (audio_query)...' });

    const queryRes = await fetch(
      `${VOICEVOX_URL}/audio_query?text=${encodeURIComponent(text)}&speaker=${speaker}`,
      { method: 'POST' }
    );
    if (!queryRes.ok) {
      send({ type: 'error', detail: `audio_query failed: ${await queryRes.text()}` });
      res.end(); return;
    }
    const query = await queryRes.json();

    if (speedScale      !== undefined) query.speedScale      = parseFloat(speedScale);
    if (pitchScale      !== undefined) query.pitchScale      = parseFloat(pitchScale);
    if (intonationScale !== undefined) query.intonationScale = parseFloat(intonationScale);
    if (volumeScale     !== undefined) query.volumeScale     = parseFloat(volumeScale);
    if (outputSamplingRate !== undefined) query.outputSamplingRate = parseInt(outputSamplingRate);
    if (outputStereo    !== undefined) query.outputStereo    = Boolean(outputStereo);

    send({ type: 'progress', percent: 60, desc: '音声合成中 (synthesis)...' });

    const synthRes = await fetch(
      `${VOICEVOX_URL}/synthesis?speaker=${speaker}`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(query) }
    );
    if (!synthRes.ok) {
      send({ type: 'error', detail: `synthesis failed: ${await synthRes.text()}` });
      res.end(); return;
    }

    send({ type: 'progress', percent: 90, desc: '音声ファイル保存中...' });

    const filename = `${timestamp()}.wav`;
    const outputPath = path.join(OUTPUT_DIR, filename);
    const buf = Buffer.from(await synthRes.arrayBuffer());
    fs.writeFileSync(outputPath, buf);

    send({ type: 'done', model: 'VOICEVOX', speaker, audioUrl: `/outputs/${filename}` });
  } catch (e) {
    console.error('[VOICEVOX] stream error:', e.message);
    send({ type: 'error', detail: e.message });
  }

  res.end();
});

app.listen(PORT, '127.0.0.1', () => {
  console.log(`Node API listening on http://127.0.0.1:${PORT}`);
  console.log(`Using VOICEVOX engine: ${VOICEVOX_URL}`);
});
