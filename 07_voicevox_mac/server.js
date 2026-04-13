const express = require('express');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { execFileSync } = require('child_process');

const SPLIT_THRESHOLD = 500; // 超过此字数才分段
const SEGMENT_MAX_LEN = 360; // 每段字数上限

// 按「、」切分后，贪心拼接成每段 ≤ SEGMENT_MAX_LEN 的分段数组
function buildSegments(text) {
  const clauses = text.split('、').reduce((acc, c, i, arr) => {
    acc.push(i < arr.length - 1 ? c + '、' : c);
    return acc;
  }, []).filter(s => s.length > 0);

  const segments = [];
  let current = '';
  for (const clause of clauses) {
    if (current.length + clause.length <= SEGMENT_MAX_LEN) {
      current += clause;
    } else {
      if (current) segments.push(current);
      current = clause; // 单个 clause 超过上限时直接作为一段
    }
  }
  if (current) segments.push(current);
  return segments;
}

function mergeWavFiles(segPaths, outputPath) {
  const listFile = path.join(os.tmpdir(), `vv_concat_${Date.now()}.txt`);
  fs.writeFileSync(listFile, segPaths.map(p => `file '${p}'`).join('\n'));
  try {
    execFileSync('ffmpeg', ['-y', '-f', 'concat', '-safe', '0', '-i', listFile, '-c', 'copy', outputPath]);
  } finally {
    fs.unlinkSync(listFile);
    segPaths.forEach(p => { try { fs.unlinkSync(p); } catch (_) {} });
  }
}

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

app.get('/health', async (_req, res) => {
  let vvReady = false, vvVersion = null;
  try {
    const r = await fetch(`${VOICEVOX_URL}/version`);
    if (r.ok) { vvVersion = await r.text(); vvReady = true; }
  } catch (_) {}
  res.json({ node: true, voicevox: vvReady, voicevox_version: vvVersion, voicevox_url: VOICEVOX_URL });
});

// ---------------------------------------------------------------------------
// Speakers proxy
// ---------------------------------------------------------------------------

app.get('/speakers', async (_req, res) => {
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
// 単セグメント合成ヘルパー
// ---------------------------------------------------------------------------

async function synthesizeOne(segText, speaker, params) {
  const qr = await fetch(
    `${VOICEVOX_URL}/audio_query?text=${encodeURIComponent(segText)}&speaker=${speaker}`,
    { method: 'POST' }
  );
  if (!qr.ok) throw new Error(`audio_query failed: ${await qr.text()}`);
  const query = await qr.json();

  const { speedScale, pitchScale, intonationScale, volumeScale, outputSamplingRate, outputStereo } = params;
  if (speedScale         !== undefined) query.speedScale         = parseFloat(speedScale);
  if (pitchScale         !== undefined) query.pitchScale         = parseFloat(pitchScale);
  if (intonationScale    !== undefined) query.intonationScale    = parseFloat(intonationScale);
  if (volumeScale        !== undefined) query.volumeScale        = parseFloat(volumeScale);
  if (outputSamplingRate !== undefined) query.outputSamplingRate = parseInt(outputSamplingRate);
  if (outputStereo       !== undefined) query.outputStereo       = Boolean(outputStereo);

  const sr = await fetch(
    `${VOICEVOX_URL}/synthesis?speaker=${speaker}`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(query) }
  );
  if (!sr.ok) throw new Error(`synthesis failed: ${await sr.text()}`);
  return Buffer.from(await sr.arrayBuffer());
}

// ---------------------------------------------------------------------------
// TTS (sync)
// ---------------------------------------------------------------------------

app.post('/tts', async (req, res) => {
  const { text, speaker, speedScale, pitchScale, intonationScale, volumeScale, outputSamplingRate, outputStereo } = req.body || {};

  if (!text || !String(text).trim()) { res.status(400).json({ error: 'text is required' }); return; }
  if (speaker === undefined || speaker === null) { res.status(400).json({ error: 'speaker is required' }); return; }

  const src = String(text).trim();
  const params = { speedScale, pitchScale, intonationScale, volumeScale, outputSamplingRate, outputStereo };
  const ts = timestamp();

  try {
    if (src.length <= SPLIT_THRESHOLD) {
      const buf = await synthesizeOne(src, speaker, params);
      const filename = `${ts}.wav`;
      fs.writeFileSync(path.join(OUTPUT_DIR, filename), buf);
      res.json({ message: 'ok', model: 'VOICEVOX', speaker, segments: 1, audioUrl: `/outputs/${filename}` });
    } else {
      const segments = buildSegments(src);
      console.log(`[VOICEVOX] 分段合成: ${src.length}字 → ${segments.length}段`);
      const segPaths = [];
      for (let i = 0; i < segments.length; i++) {
        console.log(`  段${i + 1}/${segments.length}(${segments[i].length}字): ${segments[i]}`);
        const buf = await synthesizeOne(segments[i], speaker, params);
        const segPath = path.join(os.tmpdir(), `vv_seg_${ts}_${i}.wav`);
        fs.writeFileSync(segPath, buf);
        segPaths.push(segPath);
      }
      const filename = `${ts}.wav`;
      mergeWavFiles(segPaths, path.join(OUTPUT_DIR, filename));
      res.json({ message: 'ok', model: 'VOICEVOX', speaker, segments: segments.length, audioUrl: `/outputs/${filename}` });
    }
  } catch (e) {
    console.error('[VOICEVOX] tts error:', e.message);
    res.status(500).json({ error: e.message });
  }
});

// ---------------------------------------------------------------------------
// TTS (SSE stream)
// ---------------------------------------------------------------------------

app.post('/tts/stream', async (req, res) => {
  const { text, speaker, speedScale, pitchScale, intonationScale, volumeScale, outputSamplingRate, outputStereo } = req.body || {};

  if (!text || !String(text).trim()) { res.status(400).json({ error: 'text is required' }); return; }
  if (speaker === undefined || speaker === null) { res.status(400).json({ error: 'speaker is required' }); return; }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('X-Accel-Buffering', 'no');

  const send = (obj) => res.write(`data: ${JSON.stringify(obj)}\n\n`);
  const src = String(text).trim();
  const params = { speedScale, pitchScale, intonationScale, volumeScale, outputSamplingRate, outputStereo };
  const ts = timestamp();

  console.log(`[VOICEVOX] 合成テキスト(${src.length}字): ${src}`);

  try {
    if (src.length <= SPLIT_THRESHOLD) {
      send({ type: 'progress', percent: 20, desc: 'テキスト解析中 (audio_query)...' });
      const buf = await synthesizeOne(src, speaker, params);
      send({ type: 'progress', percent: 90, desc: '音声ファイル保存中...' });
      const filename = `${ts}.wav`;
      fs.writeFileSync(path.join(OUTPUT_DIR, filename), buf);
      send({ type: 'done', model: 'VOICEVOX', speaker, segments: 1, audioUrl: `/outputs/${filename}` });
    } else {
      const segments = buildSegments(src);
      console.log(`[VOICEVOX] 分段合成: ${src.length}字 → ${segments.length}段`);
      send({ type: 'progress', percent: 5, desc: `テキストを ${segments.length} 段落に分割しました` });
      const segPaths = [];
      for (let i = 0; i < segments.length; i++) {
        console.log(`  段${i + 1}/${segments.length}(${segments[i].length}字): ${segments[i]}`);
        const percent = Math.round(5 + (i / segments.length) * 80);
        send({ type: 'progress', percent, desc: `合成中 ${i + 1}/${segments.length}` });
        const buf = await synthesizeOne(segments[i], speaker, params);
        const segPath = path.join(os.tmpdir(), `vv_seg_${ts}_${i}.wav`);
        fs.writeFileSync(segPath, buf);
        segPaths.push(segPath);
      }
      send({ type: 'progress', percent: 90, desc: '音声ファイルを結合中 (ffmpeg)...' });
      const filename = `${ts}.wav`;
      mergeWavFiles(segPaths, path.join(OUTPUT_DIR, filename));
      send({ type: 'done', model: 'VOICEVOX', speaker, segments: segments.length, audioUrl: `/outputs/${filename}` });
    }
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
