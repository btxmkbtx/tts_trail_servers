const express = require('express');
const path = require('path');
const fs = require('fs');
function timestamp() {
  const d = new Date();
  const pad = (n, l = 2) => String(n).padStart(l, '0');
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

const app = express();
const PORT = Number(process.env.PORT || 3009);
const PYTHON_SERVICE_URL = process.env.PYTHON_SERVICE_URL || 'http://127.0.0.1:5013';

const ROOT_DIR = __dirname;
const PUBLIC_DIR = path.join(ROOT_DIR, 'public');
const OUTPUT_DIR = path.join(ROOT_DIR, 'outputs');

for (const dirPath of [PUBLIC_DIR, OUTPUT_DIR]) {
  fs.mkdirSync(dirPath, { recursive: true });
}

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
      python: { ready: false, error: error.message },
    });
  }
});

app.get('/models', async (_req, res) => {
  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/models`);
    const payload = await response.json();
    res.status(response.status).json(payload);
  } catch (error) {
    res.status(503).json({ error: error.message });
  }
});

app.get('/models/:name', async (req, res) => {
  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/models/${encodeURIComponent(req.params.name)}`);
    const payload = await response.json();
    res.status(response.status).json(payload);
  } catch (error) {
    res.status(503).json({ error: error.message });
  }
});

app.post('/tts', async (req, res) => {
  const {
    text, model_name, language, speaker_id, style,
    style_weight, length, sdp_ratio, noise, noisew,
  } = req.body || {};

  if (!text || !String(text).trim()) {
    res.status(400).json({ error: 'text is required' });
    return;
  }
  if (!model_name) {
    res.status(400).json({ error: 'model_name is required' });
    return;
  }

  const outputFilename = `${timestamp()}.wav`;
  const outputPath = path.join(OUTPUT_DIR, outputFilename);

  try {
    const response = await fetch(`${PYTHON_SERVICE_URL}/synthesize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text, model_name, language, speaker_id, style,
        style_weight, length, sdp_ratio, noise, noisew,
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
      model: payload.model,
      device: payload.device,
    });
  } catch (error) {
    res.status(500).json({ error: 'failed to call python SBV2 service', detail: error.message });
  }
});

app.post('/tts/stream', async (req, res) => {
  const {
    text, model_name, language, speaker_id, style,
    style_weight, length, sdp_ratio, noise, noisew,
  } = req.body || {};

  if (!text || !String(text).trim()) {
    res.status(400).json({ error: 'text is required' });
    return;
  }
  if (!model_name) {
    res.status(400).json({ error: 'model_name is required' });
    return;
  }

  const outputFilename = `${timestamp()}.wav`;
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
        text, model_name, language, speaker_id, style,
        style_weight, length, sdp_ratio, noise, noisew,
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
