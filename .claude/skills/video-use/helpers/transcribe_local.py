"""Transcrição LOCAL e GRATUITA (faster-whisper) — alternativa ao ElevenLabs Scribe.

Gera JSON no MESMO formato do Scribe (lista `words` com type word/spacing,
start/end em segundos, speaker_id), então pack_transcripts.py e render.py
funcionam sem mudança nenhuma.

Uso:
    python helpers/transcribe_local.py <video> [--edit-dir DIR] [--language pt] [--model small]

Modelos: tiny | base | small (padrão, bom em PT-BR) | medium | large-v3
Cache: se o JSON já existe, não transcreve de novo (Hard Rule 9).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def extract_audio(video: Path, wav: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "16000", str(wav)],
        check=True,
    )


def transcribe(video: Path, edit_dir: Path, language: str | None, model_name: str) -> Path:
    out_dir = edit_dir / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{video.stem}.json"
    if out.exists():
        print(f"[cache] {out}")
        return out

    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="auto", compute_type="int8")
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "a.wav"
        extract_audio(video, wav)
        segments, info = model.transcribe(
            str(wav),
            language=language,
            word_timestamps=True,
            vad_filter=False,          # não “limpa” silêncios: precisamos deles p/ cortar
            condition_on_previous_text=False,
        )
        words: list[dict] = []
        prev_end = 0.0
        for seg in segments:
            for w in seg.words or []:
                start, end = float(w.start), float(w.end)
                if start > prev_end:
                    words.append({"text": " ", "start": round(prev_end, 3),
                                  "end": round(start, 3), "type": "spacing",
                                  "speaker_id": "speaker_0"})
                words.append({"text": w.word.strip(), "start": round(start, 3),
                              "end": round(end, 3), "type": "word",
                              "speaker_id": "speaker_0",
                              "logprob": round(float(w.probability), 3)})
                prev_end = end

    data = {
        "language_code": info.language,
        "language_probability": info.language_probability,
        "text": " ".join(w["text"] for w in words if w["type"] == "word"),
        "words": words,
        "source": str(video),
        "engine": f"faster-whisper:{model_name}",
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(f"[ok] {out}  ({sum(w['type']=='word' for w in words)} palavras, lang={info.language})")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--edit-dir", type=Path, default=None)
    ap.add_argument("--language", default="pt")
    ap.add_argument("--model", default="small")
    a = ap.parse_args()
    if not a.video.exists():
        sys.exit(f"não achei: {a.video}")
    edit_dir = a.edit_dir or a.video.resolve().parent / "edit"
    transcribe(a.video.resolve(), edit_dir, a.language or None, a.model)


if __name__ == "__main__":
    main()
