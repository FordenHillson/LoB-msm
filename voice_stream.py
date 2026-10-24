import json
import queue
import threading
import time
from collections import deque

import numpy as np
from discord.ext import voice_recv

OPUS_SILENCE = bytes([0xF8, 0xFF, 0xFE])
FRAME_BYTES = 3840  # 20ms of 48kHz stereo s16le
FRAME_SECONDS = 0.02
SEGMENT_GAP = 0.8  # seconds of silence that ends a speaker segment (client subtracts this)
MAX_USER_BACKLOG = 10  # frames kept per speaker before dropping oldest


class VoiceHub:
    """Fans mixed PCM frames (and speaker info) out to connected dashboard listeners."""

    def __init__(self):
        self._lock = threading.Lock()
        self._listeners = set()
        self.channel_name = None
        self.speakers = {}  # user name -> last time spoke

    def add_listener(self):
        q = queue.Queue(maxsize=50)
        with self._lock:
            self._listeners.add(q)
        return q

    def remove_listener(self, q):
        with self._lock:
            self._listeners.discard(q)

    def listener_count(self):
        with self._lock:
            return len(self._listeners)

    def publish(self, item):
        with self._lock:
            listeners = list(self._listeners)
        for q in listeners:
            try:
                q.put_nowait(item)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(item)
                except (queue.Empty, queue.Full):
                    pass

    def active_speakers(self, within=2.0):
        now = time.monotonic()
        return sorted(n for n, t in self.speakers.items() if now - t <= within)

    def status(self):
        return {
            "connected": self.channel_name is not None,
            "channel": self.channel_name,
            "speakers": self.active_speakers(),
            "listeners": self.listener_count(),
        }


hub = VoiceHub()


class MixingSink(voice_recv.AudioSink):
    """Buffers PCM per speaker and mixes one frame per 20ms tick into the hub."""

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._buffers = {}
        self._open = {}  # speaker name -> user id string, for speaker segment events
        self._last_heard = {}
        self._running = True
        self._thread = threading.Thread(target=self._mix_loop, daemon=True)
        self._thread.start()

    def wants_opus(self):
        return False

    def write(self, user, data):
        if user is None or not data.pcm:
            return
        name = getattr(user, "display_name", str(user))
        with self._lock:
            buf = self._buffers.setdefault(name, deque(maxlen=MAX_USER_BACKLOG))
            buf.append(data.pcm)
        now = time.monotonic()
        hub.speakers[name] = now
        self._last_heard[name] = now
        if name not in self._open:
            self._open[name] = str(getattr(user, "id", ""))
            hub.publish(json.dumps({"event": "start", "speaker": name, "user_id": self._open[name]}))

    def _mix_loop(self):
        next_tick = time.monotonic()
        last_names = None
        while self._running:
            next_tick += FRAME_SECONDS
            frames = []
            with self._lock:
                for buf in self._buffers.values():
                    if buf:
                        frames.append(buf.popleft())
            if frames and hub.listener_count():
                mixed = np.zeros(FRAME_BYTES // 2, dtype=np.int32)
                for f in frames:
                    arr = np.frombuffer(f, dtype=np.int16)
                    mixed[: len(arr)] += arr
                pcm = np.clip(mixed, -32768, 32767).astype(np.int16).tobytes()
                hub.publish(pcm)
            now = time.monotonic()
            for name in [n for n in self._open if now - self._last_heard[n] >= SEGMENT_GAP]:
                uid = self._open.pop(name)
                hub.publish(json.dumps({"event": "end", "speaker": name, "user_id": uid}))
            names = hub.active_speakers()
            if names != last_names:
                last_names = names
                hub.publish(json.dumps({"speakers": names}))
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = time.monotonic()

    def cleanup(self):
        self._running = False


def install_dave_decrypt(vc):
    """voice_recv only strips transport encryption; Discord's DAVE E2EE layer must be removed too."""
    import davey

    decryptor = vc._reader.decryptor
    transport_decrypt = decryptor.decrypt_rtp
    stats = {"ok": 0, "fail": 0}

    def decrypt_rtp(packet):
        data = transport_decrypt(packet)
        conn = vc._connection
        session = getattr(conn, "dave_session", None)
        if session is None or not conn.dave_protocol_version:
            return data
        user_id = vc._ssrc_to_id.get(packet.ssrc)
        if not session.ready or user_id is None:
            return OPUS_SILENCE  # still encrypted; feeding it to opus would corrupt the stream
        try:
            out = session.decrypt(user_id, davey.MediaType.audio, data)
            stats["ok"] += 1
            return bytes(out)
        except Exception as e:
            stats["fail"] += 1
            if stats["fail"] in (1, 50, 500):
                print(f"DAVE decrypt failed ({stats}): {type(e).__name__}: {e}")
            return OPUS_SILENCE

    decryptor.decrypt_rtp = decrypt_rtp


def harden_opus_decoder():
    """One bad packet raises OpusError and makes voice_recv stop listening entirely; emit silence instead."""
    from discord.ext.voice_recv import opus as vr_opus
    from discord.opus import OpusError

    cls = vr_opus.PacketDecoder
    if getattr(cls, "_hardened", False):
        return
    original = cls._decode_packet

    def safe_decode(self, packet):
        try:
            return original(self, packet)
        except OpusError:
            return packet, bytes(FRAME_BYTES)

    cls._decode_packet = safe_decode
    cls._hardened = True
