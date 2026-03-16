const express = require('express');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const { randomUUID } = require('crypto');

const app = express();
const PORT = Number(process.env.PORT || 3007);
const PYTHON_SERVICE_URL = process.env.PYTHON_SERVICE_URL || 'http://127.0.0.1:5001';

const ROOT_DIR = __dirname;
const PUBLIC_DIR = path.join(ROOT_DIR, 'public');
const UPLOAD_DIR = path.join(ROOT_DIR, 'uploads');
const OUTPUT_DIR = path.join(ROOT_DIR, 'outputs');

fs.mkdirSync(PUBLIC_DIR, { recursive: true });
fs.mkdirSync(UPLOAD_DIR, { recursive: true });
fs.mkdirSync(OUTPUT_DIR, { recursive: true });

const storage = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, UPLOAD_DIR),
  filename: (_req, file, cb) => {
    const ext = path.extname(file.originalname) || '.wav';
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
    const pythonHealth = await response.json();
    res.json({
      status: 'ok',
      node: 'ready',
      python: pythonHealth,
    });
  } catch (error) {
    res.status(503).json({
      status: 'degraded',
      message: 'Python XTTS service is not reachable.',
      error: error.message,
    });
  }
});

app.get('/voices', async (_req, res) => {
  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/voices`);
    const payload = await response.json();

    if (!response.ok) {
      res.status(response.status).json(payload);
      return;
    }

    res.json(payload);
  } catch (error) {
    res.status(500).json({
      error: 'failed to load voices',
      detail: error.message,
    });
  }
});

app.post('/voices/register', upload.single('speaker'), async (req, res) => {
  const speakerFile = req.file;
  const voiceId = (req.body?.voice_id || '').trim() || undefined;

  if (!speakerFile) {
    res.status(400).json({ error: 'speaker file is required (multipart field name: speaker)' });
    return;
  }

  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/voices/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        speaker_wav_path: speakerFile.path,
        speaker_original_name: speakerFile.originalname,
        voice_id: voiceId,
      }),
    });

    const payload = await response.json();

    if (!response.ok) {
      res.status(response.status).json(payload);
      return;
    }

    res.json({
      message: 'ok',
      voiceId: payload.voice_id,
      normalizedSpeakerSample: payload.normalized_speaker_path
        ? path.basename(payload.normalized_speaker_path)
        : null,
    });
  } catch (error) {
    res.status(500).json({
      error: 'failed to register voice',
      detail: error.message,
    });
  }
});

app.post('/tts', upload.single('speaker'), async (req, res) => {
  const { text, language = 'ja', voice_id: requestedVoiceId = '' } = req.body;
  const speakerFile = req.file;
  const voiceId = requestedVoiceId.trim();

  if (!text || !text.trim()) {
    res.status(400).json({ error: 'text is required' });
    return;
  }

  if (!speakerFile && !voiceId) {
    res.status(400).json({ error: 'speaker file or voice_id is required' });
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
        speaker_wav_path: speakerFile?.path,
        speaker_original_name: speakerFile?.originalname,
        voice_id: voiceId || undefined,
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
      speakerSample: speakerFile ? path.basename(speakerFile.path) : null,
      voiceId: payload.voice_id || null,
      voiceSource: payload.voice_source || null,
      normalizedSpeakerSample: payload.normalized_speaker_path
        ? path.basename(payload.normalized_speaker_path)
        : null,
      language,
      model: payload.model,
    });
  } catch (error) {
    res.status(500).json({
      error: 'failed to call python xtts service',
      detail: error.message,
    });
  }
});

app.listen(PORT, () => {
  console.log(`Node API listening on http://127.0.0.1:${PORT}`);
  console.log(`Using Python service: ${PYTHON_SERVICE_URL}`);
});
