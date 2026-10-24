"""Fill the `text` of each speaker segment in a Voice Monitor JSON by transcribing its WAV locally.

    python transcribe.py meeting.json [--wav meeting.wav] [--model small] [--language th]

Each segment is transcribed from its own speaker's track (the per-speaker WAVs listed under "tracks"
in the JSON, next to it). Segments without a track fall back to the mixed WAV.

Writes meeting.transcribed.json and meeting.transcribed.txt next to the input JSON.
"""
import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

for _stream in (sys.stdout, sys.stderr):  # Windows consoles default to a codepage that cannot print Thai
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

TARGET_RATE = 16000
PAD_SECONDS = 0.2  # context kept around each segment so word edges are not clipped
SILENCE_PEAK = 0.005  # clips quieter than this are skipped (engines tend to invent text for silence)
GEMINI_MODEL = "gemini-3.8-flash"  # name suggested by Google's API when 2.5-flash was retired; change with --gemini-model
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def load_wav(path):
    """Return (mono float32 samples, sample rate)."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            sys.exit("Only 16-bit PCM WAV is supported")
        rate, channels, frames = w.getframerate(), w.getnchannels(), w.getnframes()
        raw = w.readframes(frames)
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def resample(samples, rate, target=TARGET_RATE):
    if rate == target:
        return samples
    n_out = int(len(samples) * target / rate)
    positions = np.linspace(0, len(samples) - 1, n_out)
    return np.interp(positions, np.arange(len(samples)), samples).astype(np.float32)


def cut_segment(audio, rate, start, end):
    a = max(0, int((start - PAD_SECONDS) * rate))
    b = min(len(audio), int((end + PAD_SECONDS) * rate))
    return audio[a:b]


class AudioSource:
    """Finds the audio for a segment: the speaker's own track if present, else the mixed WAV."""

    def __init__(self, json_path, data, mix_path=None):
        self.folder = Path(json_path).parent
        self.tracks = data.get("tracks") or {}
        self.mix_path = Path(mix_path) if mix_path else (self.folder / data["audio_file"] if data.get("audio_file") else None)
        self._cache = {}

    def _load(self, path):
        key = str(path)
        if key not in self._cache:
            self._cache[key] = load_wav(path)
        return self._cache[key]

    def uses_track(self, speaker):
        name = self.tracks.get(speaker)
        return bool(name) and (self.folder / name).is_file()

    def for_segment(self, seg):
        if self.uses_track(seg["speaker"]):
            return self._load(self.folder / self.tracks[seg["speaker"]])
        if self.mix_path is None or not self.mix_path.is_file():
            raise FileNotFoundError(f"No audio for speaker '{seg['speaker']}': track and mixed WAV not found next to the JSON")
        return self._load(self.mix_path)


def fill_segments(data, audio_for, transcribe, overwrite=False, log=print, progress=None, cancelled=None):
    """transcribe(16kHz float32 array) -> str. Mutates and returns data."""
    segments = data.get("segments", [])
    for i, seg in enumerate(segments, 1):
        if cancelled and cancelled():
            raise InterruptedError("cancelled")
        if progress:
            progress(i - 1, len(segments))
        if seg.get("text") and not overwrite:
            continue
        audio, rate = audio_for(seg)
        clip = resample(cut_segment(audio, rate, seg["start"], seg["end"]), rate)
        audible = len(clip) >= TARGET_RATE * 0.2 and float(np.abs(clip).max()) >= SILENCE_PEAK
        seg["text"] = transcribe(clip).strip() if audible else ""
        note = getattr(transcribe, "last_note", "") if not seg["text"] else ""
        log(f"[{i}/{len(segments)}] {seg['start']:.1f}s {seg['speaker']}: {seg['text']} {note}".rstrip())
    if progress:
        progress(len(segments), len(segments))
    return data


def save_outputs(data, json_path):
    out_json = Path(json_path).with_suffix(".transcribed.json")
    out_txt = Path(json_path).with_suffix(".transcribed.txt")
    out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    out_txt.write_text(format_txt(data), encoding="utf-8")
    return out_json, out_txt


def format_txt(data):
    lines = []
    for seg in sorted(data.get("segments", []), key=lambda s: s["start"]):
        m, s = divmod(seg["start"], 60)
        if seg.get("text"):
            lines.append(f"[{int(m):02d}:{s:04.1f}] {seg['speaker']}: {seg['text']}")
    return "\n".join(lines) + "\n"


def wav_bytes(clip, rate=TARGET_RATE):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(clip, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


LANGUAGE_NAMES = {"th": "ไทย", "en": "อังกฤษ"}


def gemini_prompt(language, glossary):
    lang = LANGUAGE_NAMES.get(language)
    prompt = (
        f"ถอดเสียงพูดในไฟล์เสียงนี้เป็นข้อความภาษา{lang} " if lang else "ถอดเสียงพูดในไฟล์เสียงนี้เป็นข้อความ "
    ) + (
        "ตามที่ได้ยินจริงทุกคำ ห้ามสรุป ห้ามแปล ห้ามเพิ่มคำอธิบาย ตอบเฉพาะข้อความที่พูด "
        "คำอังกฤษให้เขียนเป็นอักษรอังกฤษ ถ้าไม่มีเสียงพูดที่ชัดเจนให้ตอบว่างเปล่า"
    )
    if glossary:
        prompt += f" คำเฉพาะที่อาจพบในเสียง (สะกดตามนี้): {glossary}"
    return prompt


def make_gemini(model_name, language, glossary="", api_key=None, retries=3):
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("ไม่พบ Gemini API key: ตั้งตัวแปร GEMINI_API_KEY หรือกรอกในช่อง API key")
    url = GEMINI_URL.format(model=model_name)
    prompt = gemini_prompt(language, glossary)

    def transcribe(clip):
        body = json.dumps({
            "contents": [{"parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "audio/wav", "data": base64.b64encode(wav_bytes(clip)).decode()}},
            ]}],
            "generationConfig": {"temperature": 0},
        }).encode()
        # key goes in a header, never in the URL
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise RuntimeError(f"Gemini HTTP {e.code}: {detail}") from None
            except (TimeoutError, urllib.error.URLError) as e:  # read timeout / dropped connection
                if attempt < retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise RuntimeError(f"Gemini request failed after {retries + 1} tries: {type(e).__name__}: {e}") from None
        candidates = payload.get("candidates") or []
        parts = (candidates[0].get("content") or {}).get("parts", []) if candidates else []
        text = "".join(p.get("text", "") for p in parts)
        reason = candidates[0].get("finishReason") if candidates else (payload.get("promptFeedback") or {}).get("blockReason", "NO_CANDIDATES")
        transcribe.last_note = "" if text or reason in (None, "STOP") else f"(Gemini finishReason={reason})"
        return text

    return transcribe


def make_whisper(model_name, language, gpu=False, glossary=""):
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cuda" if gpu else "cpu", compute_type="float16" if gpu else "int8")

    def transcribe(clip):
        parts, _ = model.transcribe(clip, language=language, beam_size=5, vad_filter=True, initial_prompt=glossary or None)
        return " ".join(p.text.strip() for p in parts)

    return transcribe


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json")
    ap.add_argument("--wav", help="mixed WAV (default: audio_file from the JSON, next to it)")
    ap.add_argument("--model", default="small", help="tiny/base/small/medium/large-v3 (bigger = more accurate, slower)")
    ap.add_argument("--language", default="th", help="language code, e.g. th, en ('auto' to detect)")
    ap.add_argument("--engine", choices=["local", "gemini"], default="local", help="local Whisper (offline) or Gemini (sends audio to Google; needs GEMINI_API_KEY)")
    ap.add_argument("--gemini-model", default=GEMINI_MODEL)
    ap.add_argument("--glossary", default="", help="special words to help recognition, e.g. 'Boss, Absolab, Exaltation'")
    ap.add_argument("--gpu", action="store_true", help="use NVIDIA CUDA (needs CUDA 12 cuBLAS/cuDNN installed); default is CPU")
    ap.add_argument("--overwrite", action="store_true", help="re-transcribe segments that already have text")
    args = ap.parse_args()

    json_path = Path(args.json)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    source = AudioSource(json_path, data, args.wav)
    language = None if args.language == "auto" else args.language

    if args.engine == "gemini":
        print(f"Using Gemini '{args.gemini_model}': audio is sent to Google")
        transcribe = make_gemini(args.gemini_model, language, args.glossary)
    else:
        print(f"Loading model '{args.model}' (first run downloads it)...")
        transcribe = make_whisper(args.model, language, gpu=args.gpu, glossary=args.glossary)
    fill_segments(data, source.for_segment, transcribe, overwrite=args.overwrite)

    out_json, out_txt = save_outputs(data, json_path)
    print(f"Done:\n  {out_json}\n  {out_txt}")


if __name__ == "__main__":
    main()
