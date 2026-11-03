#!/usr/bin/env python3
"""tiktok.py — pipeline rápido de vídeo curto (TikTok / Reels / Shorts), PT-BR.

Subcomandos
  probe     <video>                       → info (duração, resolução, fps, loudness)
  autocut   <video> [--transcript J]      → edit/edl.json + edit/cut.mp4  (jump cuts)
  reframe   <video> -o OUT [--mode blur|crop|fit]  → 1080x1920
  captions  <video> --words W.json -o OUT [--style hormozi|clean|neon]
  pipeline  <video> [--transcript J]      → autocut → reframe → captions → loudnorm → final.mp4

Sem transcrição, o autocut usa silencedetect do ffmpeg (funciona offline,
sem chave de API). Com transcrição (Scribe ou transcribe_local.py), corta
em limite de palavra, remove muletas (“tipo”, “né”, “éé”) e gera legendas
palavra-a-palavra.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

W, H = 1080, 1920
FILLERS = {"é", "éé", "ééé", "hã", "hmm", "hum", "ahn", "ah", "eh", "tipo", "né", "então", "aí", "uh", "um", "uhm"}
SOFT_FILLERS = {"então", "aí", "tipo", "né"}  # só removidos com --aggressive


def run(cmd: list[str], capture: bool = False) -> str:
    r = subprocess.run(cmd, check=True, text=True,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None)
    return (r.stdout or "") + (r.stderr or "") if capture else ""


def probe(video: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video)], capture=True)
    d = json.loads(out)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        rot = int(sd.get("rotation", 0) or 0)
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    if abs(rot) == 90:
        w, h = h, w
    num, den = (v.get("r_frame_rate", "30/1").split("/") + ["1"])[:2]
    return {"duration": float(d["format"]["duration"]), "width": w, "height": h,
            "fps": round(float(num) / float(den or 1), 3), "has_audio": a is not None}


# ---------------------------------------------------------------- autocut
def silences_ffmpeg(video: Path, noise_db: float, min_sil: float) -> list[tuple[float, float]]:
    out = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-af",
               f"silencedetect=noise={noise_db}dB:d={min_sil}", "-f", "null", "-"], capture=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    if len(ends) < len(starts):
        ends.append(probe(video)["duration"])
    return list(zip(starts, ends))


def keep_from_silences(dur: float, sil: list[tuple[float, float]], pad: float) -> list[tuple[float, float]]:
    keep, t = [], 0.0
    for s, e in sil:
        a, b = t, min(dur, s + pad)
        if b - a > 0.15:
            keep.append((max(0.0, a), b))
        t = max(0.0, e - pad)
    if dur - t > 0.15:
        keep.append((t, dur))
    return keep


def load_words(path: Path) -> list[dict]:
    d = json.loads(path.read_text())
    words = d["words"] if isinstance(d, dict) else d
    return [w for w in words if w.get("type", "word") == "word" and (w.get("text") or "").strip()]


def norm(t: str) -> str:
    return re.sub(r"[^\wà-ú]", "", t.lower())


def keep_from_words(words: list[dict], max_gap: float, pad_in: float, pad_out: float,
                    aggressive: bool) -> tuple[list[tuple[float, float]], list[dict]]:
    fillers = FILLERS if aggressive else FILLERS - SOFT_FILLERS
    kept = [w for w in words if norm(w["text"]) not in fillers]
    ranges: list[list[float]] = []
    for w in kept:
        s, e = float(w["start"]), float(w["end"])
        if ranges and s - ranges[-1][1] <= max_gap:
            ranges[-1][1] = e
        else:
            ranges.append([s, e])
    out = [(max(0.0, a - pad_in), b + pad_out) for a, b in ranges]
    # junta faixas que encostaram por causa do padding
    merged: list[list[float]] = []
    for a, b in out:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged], kept


def remap_words(kept: list[dict], ranges: list[tuple[float, float]]) -> list[dict]:
    """Converte tempo da fonte → tempo de saída (Hard Rule 5 do video-use)."""
    out, offset = [], 0.0
    for a, b in ranges:
        for w in kept:
            if w["start"] >= a - 1e-3 and w["end"] <= b + 1e-3:
                out.append({"text": w["text"].strip(),
                            "start": round(w["start"] - a + offset, 3),
                            "end": round(w["end"] - a + offset, 3)})
        offset += b - a
    return out


def render_ranges(video: Path, ranges: list[tuple[float, float]], out: Path) -> None:
    """Extrai cada trecho com fade de 30ms (sem estalo) e concatena sem reencodar."""
    has_audio = probe(video)["has_audio"]
    with tempfile.TemporaryDirectory() as td:
        parts = []
        for i, (a, b) in enumerate(ranges):
            d = b - a
            p = Path(td) / f"s{i:04d}.mp4"
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.3f}", "-t", f"{d:.3f}", "-i", str(video),
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", "30"]
            if has_audio:
                fo = max(0.0, d - 0.03)
                cmd += ["-af", f"afade=t=in:st=0:d=0.03,afade=t=out:st={fo:.3f}:d=0.03",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
            run(cmd + [str(p)])
            parts.append(p)
        lst = Path(td) / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])


def cmd_autocut(a) -> Path:
    video = Path(a.video).resolve()
    edit = Path(a.edit_dir) if a.edit_dir else video.parent / "edit"
    edit.mkdir(parents=True, exist_ok=True)
    info = probe(video)
    words_out = None
    if a.transcript:
        words = load_words(Path(a.transcript))
        ranges, kept = keep_from_words(words, a.max_gap, a.pad_in, a.pad_out, a.aggressive)
        words_out = remap_words(kept, ranges)
        mode = "transcript"
    else:
        sil = silences_ffmpeg(video, a.noise, a.min_silence)
        ranges = keep_from_silences(info["duration"], sil, a.pad_out)
        mode = "silencedetect"
    total = sum(b - a_ for a_, b in ranges)
    edl = {"version": 1, "mode": mode, "sources": {video.stem: str(video)},
           "ranges": [{"source": video.stem, "start": round(s, 3), "end": round(e, 3)} for s, e in ranges],
           "total_duration_s": round(total, 3), "original_duration_s": round(info["duration"], 3)}
    (edit / "edl.json").write_text(json.dumps(edl, ensure_ascii=False, indent=1))
    if words_out is not None:
        (edit / "words_output.json").write_text(json.dumps(words_out, ensure_ascii=False, indent=1))
    out = edit / "cut.mp4"
    render_ranges(video, ranges, out)
    print(f"[autocut:{mode}] {len(ranges)} trechos | {info['duration']:.1f}s → {total:.1f}s "
          f"(-{100 * (1 - total / info['duration']):.0f}%) → {out}")
    return out


# ---------------------------------------------------------------- reframe
def cmd_reframe(a) -> Path:
    video, out = Path(a.video), Path(a.output)
    info = probe(video)
    if info["width"] * 16 == info["height"] * 9 and a.mode != "force":
        vf = f"scale={W}:{H}"
    elif a.mode == "crop":
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    elif a.mode == "fit":
        vf = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black"
    else:  # blur — fundo desfocado, vídeo inteiro no meio (padrão TikTok)
        vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3,eq=brightness=-0.08[bg];"
              f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-filter_complex", vf + ",setsar=1,fps=30",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "copy"] if info["has_audio"] else []
    run(cmd + [str(out)])
    print(f"[reframe:{a.mode}] {info['width']}x{info['height']} → {W}x{H} → {out}")
    return out


# ---------------------------------------------------------------- captions (ASS)
STYLES = {
    # nome: (fonte, tamanho, cor base, cor destaque, contorno, sombra)
    "hormozi": ("DejaVu Sans", 92, "&H00FFFFFF", "&H0000E5FF", 7, 0),   # branco + amarelo
    "clean":   ("DejaVu Sans", 78, "&H00FFFFFF", "&H00FFFFFF", 5, 2),
    "neon":    ("DejaVu Sans", 88, "&H00FFFFFF", "&H0066FF33", 6, 0),   # verde neon
}


def ass_time(t: float) -> str:
    t = max(0.0, t)
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def chunk(words: list[dict], max_words: int, pause: float) -> list[list[dict]]:
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or len(cur) >= max_words or nxt["start"] - w["end"] >= pause or w["text"][-1:] in ".!?,":
            out.append(cur)
            cur = []
    return out


def build_ass(words: list[dict], style: str, max_words: int, y_frac: float) -> str:
    font, size, base, hi, outline, shadow = STYLES[style]
    margin_v = int(H * (1 - y_frac))
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{base},{base},&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,{outline},{shadow},2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for c in chunk(words, max_words, 0.35):
        c_end = c[-1]["end"]
        for j, w in enumerate(c):
            st = w["start"] if j else c[0]["start"]
            en = c[j + 1]["start"] if j + 1 < len(c) else c_end
            if en - st < 0.05:
                continue
            parts = []
            for k, x in enumerate(c):
                txt = x["text"].upper().replace("{", "").replace("}", "")
                if k == j:
                    # palavra ativa: cor de destaque + “pop” de escala
                    parts.append(r"{\c" + hi + r"\fscx112\fscy112}" + txt + r"{\c" + base + r"\fscx100\fscy100}")
                else:
                    parts.append(txt)
            pop = r"{\t(0,80,\fscx104\fscy104)\t(80,160,\fscx100\fscy100)}" if j == 0 else ""
            lines.append(f"Dialogue: 0,{ass_time(st)},{ass_time(en)},Cap,,0,0,0,,{pop}{' '.join(parts)}")
    return head + "\n".join(lines) + "\n"


def cmd_captions(a) -> Path:
    video, out = Path(a.video), Path(a.output)
    words = json.loads(Path(a.words).read_text())
    if isinstance(words, dict):
        words = [w for w in words["words"] if w.get("type", "word") == "word"]
    ass = out.with_suffix(".ass")
    ass.write_text(build_ass(words, a.style, a.max_words, a.y), encoding="utf-8")
    esc = str(ass.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf", f"subtitles='{esc}'",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", str(out)])
    print(f"[captions:{a.style}] {len(words)} palavras → {out}")
    return out


# ---------------------------------------------------------------- loudness
def loudnorm(video: Path, out: Path) -> None:
    """-14 LUFS / -1 dBTP — alvo das plataformas de vídeo curto."""
    if not probe(video)["has_audio"]:
        shutil.copy(video, out)
        return
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-af", "loudnorm=I=-14:TP=-1.0:LRA=11",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)])


def cmd_pipeline(a) -> None:
    video = Path(a.video).resolve()
    edit = Path(a.edit_dir) if a.edit_dir else video.parent / "edit"
    a.edit_dir = str(edit)
    cut = cmd_autocut(a)
    ns = argparse.Namespace(video=str(cut), output=str(edit / "vertical.mp4"), mode=a.mode)
    cur = cmd_reframe(ns)
    words = edit / "words_output.json"
    if words.exists() and not a.no_captions:
        cur = cmd_captions(argparse.Namespace(video=str(cur), words=str(words), output=str(edit / "captioned.mp4"),
                                              style=a.style, max_words=a.max_words, y=a.y))
    final = edit / "final.mp4"
    loudnorm(cur, final)
    i = probe(final)
    print(f"[final] {final}  {i['width']}x{i['height']} {i['duration']:.1f}s")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe"); p.add_argument("video")

    def cut_args(p):
        p.add_argument("video")
        p.add_argument("--transcript", help="JSON Scribe/transcribe_local (palavra a palavra)")
        p.add_argument("--edit-dir")
        p.add_argument("--max-gap", type=float, default=0.35, help="pausa máxima mantida entre palavras (s)")
        p.add_argument("--pad-in", type=float, default=0.05)
        p.add_argument("--pad-out", type=float, default=0.08)
        p.add_argument("--aggressive", action="store_true", help="remove também “tipo/né/então/aí”")
        p.add_argument("--noise", type=float, default=-35, help="silencedetect: limiar dB")
        p.add_argument("--min-silence", type=float, default=0.4, help="silencedetect: duração mínima (s)")

    cut_args(sub.add_parser("autocut"))

    p = sub.add_parser("reframe"); p.add_argument("video"); p.add_argument("-o", "--output", required=True)
    p.add_argument("--mode", choices=["blur", "crop", "fit", "force"], default="blur")

    def cap_args(p):
        p.add_argument("--style", choices=list(STYLES), default="hormozi")
        p.add_argument("--max-words", type=int, default=3)
        p.add_argument("--y", type=float, default=0.70, help="altura da legenda (0=topo, 1=base); 0.70 fica acima da UI do TikTok")

    p = sub.add_parser("captions"); p.add_argument("video"); p.add_argument("--words", required=True)
    p.add_argument("-o", "--output", required=True); cap_args(p)

    p = sub.add_parser("pipeline"); cut_args(p); cap_args(p)
    p.add_argument("--mode", choices=["blur", "crop", "fit", "force"], default="blur")
    p.add_argument("--no-captions", action="store_true")

    a = ap.parse_args()
    if a.cmd == "probe":
        print(json.dumps(probe(Path(a.video)), indent=1))
    else:
        {"autocut": cmd_autocut, "reframe": cmd_reframe, "captions": cmd_captions, "pipeline": cmd_pipeline}[a.cmd](a)


if __name__ == "__main__":
    main()
