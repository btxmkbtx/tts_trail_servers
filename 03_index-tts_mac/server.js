const express = require('express');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const { randomUUID } = require('crypto');

const app = express();
const PORT = Number(process.env.PORT || 3008);
const PYTHON_SERVICE_URL = process.env.PYTHON_SERVICE_URL || 'http://127.0.0.1:5012';

const ROOT_DIR = __dirname;
const PUBLIC_DIR = path.join(ROOT_DIR, 'public');
const UPLOAD_DIR = path.join(ROOT_DIR, 'uploads');
const OUTPUT_DIR = path.join(ROOT_DIR, 'outputs');

for (const dirPath of [PUBLIC_DIR, UPLOAD_DIR, OUTPUT_DIR]) {
  fs.mkdirSync(dirPath, { recursive: true });
}

const storage = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, UPLOAD_DIR),
  filename: (_req, file, cb) => {
    const ext = path.extname(file.originalname) || '.bin';
    cb(null, `${randomUUID()}${ext}`);
  },
});

const upload = multer({ storage });

app.use(express.json());
app.use(express.static(PUBLIC_DIR));
app.use('/outputs', express.static(OUTPUT_DIR));

app.get('/', (_req, res) => {
  res.sendFile(path.join(PUBLIC_DIR, 'index.html'));
});

app.get('/health', async (_req, res) => {
  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/health`);
    const payload = await response.json();
    res.status(response.status).json({
      status: response.ok ? 'ok' : 'degraded',
      node: 'ready',
      python: payload,
    });
  } catch (error) {
    res.status(503).json({
      status: 'degraded',
      node: 'ready',
      python: {
        ready: false,
        error: error.message,
      },
    });
  }
});

app.post('/tts', upload.fields([
  { name: 'speaker', maxCount: 1 },
  { name: 'emotion_speaker', maxCount: 1 },
]), async (req, res) => {
  const text = (req.body?.text || '').trim();
  const language = (req.body?.language || 'ja').trim();
  const emoText = (req.body?.emo_text || '').trim();
  const emoAlpha = req.body?.emo_alpha;
  const useEmoText = req.body?.use_emo_text === 'true';
  const useRandom = req.body?.use_random === 'true';
  const speakerFile = req.files?.speaker?.[0];
  const emotionSpeakerFile = req.files?.emotion_speaker?.[0];

  if (!text) {
    res.status(400).json({ error: 'text is required' });
    return;
  }

  if (!speakerFile) {
    res.status(400).json({ error: 'speaker file is required (multipart field name: speaker)' });
    return;
  }

  const outputFilename = `${randomUUID()}.wav`;
  const outputPath = path.join(OUTPUT_DIR, outputFilename);

  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/synthesize`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        text,
        language,
        speaker_wav_path: speakerFile.path,
        speaker_original_name: speakerFile.originalname,
        emo_audio_prompt_path: emotionSpeakerFile?.path,
        emo_audio_original_name: emotionSpeakerFile?.originalname,
        emo_alpha: emoAlpha,
        use_emo_text: useEmoText,
        emo_text: emoText || undefined,
        use_random: useRandom,
        output_path: outputPath,
      }),
    });

    const payload = await response.json();

    if (!response.ok) {
      res.status(response.status).json(payload);
      return;
    }

    res.json({
      message: 'ok',
      audioUrl: `/outputs/${outputFilename}`,
      speakerSample: path.basename(speakerFile.path),
      emotionSpeakerSample: emotionSpeakerFile ? path.basename(emotionSpeakerFile.path) : null,
      normalizedSpeakerSample: payload.normalized_speaker_path
        ? path.basename(payload.normalized_speaker_path)
        : null,
      normalizedEmotionSpeakerSample: payload.normalized_emo_audio_path
        ? path.basename(payload.normalized_emo_audio_path)
        : null,
      language,
      model: payload.model,
      runtime: payload.runtime,
      device: payload.device,
    });
  } catch (error) {
    res.status(500).json({
      error: 'failed to call python IndexTTS service',
      detail: error.message,
    });
  }
});

app.post('/tts/stream', upload.fields([
  { name: 'speaker', maxCount: 1 },
  { name: 'emotion_speaker', maxCount: 1 },
]), async (req, res) => {
  const text = (req.body?.text || '').trim();
  const language = (req.body?.language || 'ja').trim();
  const emoText = (req.body?.emo_text || '').trim();
  const emoAlpha = req.body?.emo_alpha;
  const useEmoText = req.body?.use_emo_text === 'true';
  const useRandom = req.body?.use_random === 'true';
  const speakerFile = req.files?.speaker?.[0];
  const emotionSpeakerFile = req.files?.emotion_speaker?.[0];

  if (!text) {
    res.status(400).json({ error: 'text is required' });
    return;
  }
  if (!speakerFile) {
    res.status(400).json({ error: 'speaker file is required (multipart field name: speaker)' });
    return;
  }

  const outputFilename = `${randomUUID()}.wav`;
  const outputPath = path.join(OUTPUT_DIR, outputFilename);

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  try {
    const flaskResponse = await fetch(`${PYTHON_SERVICE_URL}/synthesize/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        language,
        speaker_wav_path: speakerFile.path,
        emo_audio_prompt_path: emotionSpeakerFile?.path,
        emo_alpha: emoAlpha,
        use_emo_text: useEmoText,
        emo_text: emoText || undefined,
        use_random: useRandom,
        output_path: outputPath,
      }),
    });

    const reader = flaskResponse.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split('\n\n');
      buffer = parts.pop();

      for (const part of parts) {
        const dataLine = part.split('\n').find(l => l.startsWith('data: '));
        if (!dataLine) continue;
        try {
          const event = JSON.parse(dataLine.slice(6));
          if (event.type === 'done') {
            event.audioUrl = `/outputs/${outputFilename}`;
          }
          res.write(`data: ${JSON.stringify(event)}\n\n`);
        } catch {
          res.write(part + '\n\n');
        }
      }
    }
  } catch (error) {
    res.write(`data: ${JSON.stringify({ type: 'error', detail: error.message })}\n\n`);
  } finally {
    res.end();
  }
});

app.listen(PORT, () => {
  console.log(`Node API listening on http://127.0.0.1:${PORT}`);
  console.log(`Using Python service: ${PYTHON_SERVICE_URL}`);
});
