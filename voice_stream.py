import json
import queue
import threading
import time
from collections import deque

import numpy as np
from discord.ext import voice_recv

FRAME_BYTES = 3840  # 20ms of 48kHz stereo s16le
FRAME_SECONDS = 0.02
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
        hub.speakers[name] = time.monotonic()

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
