#!/usr/bin/env bash
# Instala dependências das skills de vídeo. Rode uma vez: bash setup.sh
set -e
command -v ffmpeg >/dev/null || { echo "Instale o ffmpeg (Windows: winget install ffmpeg | Mac: brew install ffmpeg | Linux: sudo apt install ffmpeg)"; exit 1; }
python3 -m pip install --upgrade requests librosa matplotlib pillow numpy faster-whisper yt-dlp
command -v node >/dev/null && echo "Node $(node -v) ok (Remotion/HyperFrames instalam sob demanda via npx)" || echo "Aviso: instale Node.js 22+ para Remotion/HyperFrames"
echo "Opcional: ELEVENLABS_API_KEY=... em .claude/skills/video-use/.env para transcrição mais precisa."
echo "Pronto. Coloque vídeos em videos/<projeto>/ e peça: 'edita esse vídeo pro TikTok'."
