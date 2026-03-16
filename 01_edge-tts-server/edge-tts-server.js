import express from "express"
import { exec } from "child_process"
import { v4 as uuid } from "uuid"
import fs from "fs"

const app = express()

app.use(express.json())
app.use("/audio", express.static("./audio"))

if (!fs.existsSync("./audio")) {
  fs.mkdirSync("./audio")
}

app.post("/tts", async (req, res) => {

  const { text } = req.body

  const id = uuid()
  const file = `audio/${id}.mp3`

  const cmd = `edge-tts --voice zh-CN-XiaoxiaoNeural --text "${text}" --write-media ${file}`

  exec(cmd, (err) => {

    if (err) {
      res.status(500).json({ error: err.message })
      return
    }

    res.json({
      audio_url: `http://localhost:3006/audio/${id}.mp3`
    })

  })

})

app.listen(3006, () => {
  console.log("TTS server running on 3006")
})