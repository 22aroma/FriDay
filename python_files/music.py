import json
import random
import subprocess
import sys
import threading
import time

import av
import numpy as np

from .config_loader import cfg
from .logger import log_message
from .audio_mixer import _mixer

# Быстрый поиск: flat-playlist = просто список результатов без извлечения каждого видео
_SEARCH_ARGS = [
    '--flat-playlist', '--dump-json', '--no-download',
    '--quiet', '--ignore-errors',
]

_PLAYER_CLIENTS = ['android', 'ios', 'web', 'mweb', 'tv_embedded', 'mediaconnect']

BATCH_SIZE = 20   # треков за один поиск
MIN_FILL = 5      # при таком остатке запускаем дозагрузку
MAX_QUEUE = 100
WAIT_FILL_TIMEOUT = 30  # сколько ждать дозагрузку, если очередь пуста


class MusicPlayer:
    def __init__(self):
        self._tracks = []
        self._index = 0
        self._query = "популярная музыка"
        self._lock = threading.Lock()
        self._thread = None
        self._refill_thread = None
        self._stop_event = threading.Event()
        self._skip_event = threading.Event()
        self._generation = 0
        self._current_container = None
        self._current_proc = None

    def _stopped(self, generation):
        return self._stop_event.is_set() or self._generation != generation

    def _search(self, query):
        """Быстрый поиск партии треков."""
        try:
            proc = subprocess.run(
                [sys.executable, '-m', 'yt_dlp', f'ytsearch{BATCH_SIZE}:{query}', *_SEARCH_ARGS],
                capture_output=True, text=True, timeout=20,
            )
            results = []
            for line in proc.stdout.strip().split('\n'):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    vid = data.get('id')
                    if not vid:
                        continue
                    results.append({
                        'title': data.get('title') or data.get('fulltitle') or 'Без названия',
                        'url': f"https://www.youtube.com/watch?v={vid}",
                        'id': vid,
                    })
                except json.JSONDecodeError:
                    continue
            random.shuffle(results)
            return results
        except Exception as e:
            log_message(f"Ошибка поиска: {e}", "music.py")
            return []

    def _append_unique(self, tracks):
        with self._lock:
            seen = {t['id'] for t in self._tracks}
            new = [t for t in tracks if t['id'] not in seen]
            if not new:
                new = tracks
            self._tracks.extend(new)
            if len(self._tracks) > MAX_QUEUE:
                drop = len(self._tracks) - MAX_QUEUE
                self._tracks = self._tracks[drop:]
                self._index = max(0, self._index - drop)

    def _get_stream_url(self, url):
        for client in _PLAYER_CLIENTS:
            try:
                result = subprocess.run(
                    [sys.executable, '-m', 'yt_dlp', '-f', 'bestaudio[ext=webm]/bestaudio', '-g', url,
                     '--quiet', '--no-playlist',
                     '--extractor-args', f'youtube:player_client={client}'],
                    capture_output=True, text=True, timeout=30,
                )
                raw = result.stdout.strip()
                if result.returncode == 0 and raw:
                    stream_url = raw.split('\n')[0]
                    if stream_url.startswith('http'):
                        return stream_url
            except Exception:
                pass
        return None

    def _open_via_pipe(self, url):
        try:
            proc = subprocess.Popen(
                [sys.executable, '-m', 'yt_dlp',
                 '-f', 'bestaudio', '-o', '-', url,
                 '--no-playlist', '--quiet', '--no-warnings',
                 '--extractor-args', 'youtube:player_client=android,web,mweb'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            container = av.open(proc.stdout)
            return container, proc
        except Exception as e:
            log_message(f"pipe не удался: {e}", "music.py")
            return None, None

    def _play_stream(self, url, generation):
        container = None
        pipe_proc = None

        stream_url = self._get_stream_url(url)
        if stream_url:
            try:
                container = av.open(stream_url)
            except Exception as e:
                log_message(f"av.open не удался: {e}", "music.py")

        if container is None:
            container, pipe_proc = self._open_via_pipe(url)
            if container is None:
                return False

        self._current_container = container
        self._current_proc = pipe_proc

        try:
            return self._decode_audio(container, generation)
        finally:
            if pipe_proc and pipe_proc.poll() is None:
                pipe_proc.kill()
                try:
                    pipe_proc.wait(timeout=3)
                except Exception:
                    pass
            try:
                container.close()
            except Exception:
                pass
            if self._current_container is container:
                self._current_container = None
                self._current_proc = None

    def _decode_audio(self, container, generation):
        streams = container.streams.audio
        if not streams:
            log_message("Нет аудио-стримов", "music.py")
            return False

        stream = streams[0]
        sample_rate = stream.sample_rate
        chunk_size = sample_rate * 2
        buf = []
        buf_len = 0
        frames_decoded = 0

        for frame in container.decode(stream):
            if self._stopped(generation):
                return True

            frames_decoded += 1
            arr = frame.to_ndarray()

            if arr.dtype.kind == 'i':
                arr = arr.astype(np.float32) / np.iinfo(arr.dtype).max
            else:
                arr = arr.astype(np.float32)

            if arr.ndim > 1:
                arr = arr.mean(axis=0)

            buf.append(arr)
            buf_len += len(arr)

            if buf_len >= chunk_size:
                chunk = np.concatenate(buf)
                buf = []
                buf_len = 0
                if self._generation != generation:
                    return True
                if _mixer.music_playing:
                    _mixer.append_music(chunk, sample_rate)
                else:
                    _mixer.play_music(chunk, sample_rate)

        if buf:
            chunk = np.concatenate(buf)
            if _mixer.music_playing:
                _mixer.append_music(chunk, sample_rate)
            else:
                _mixer.play_music(chunk, sample_rate)

        return frames_decoded > 0

    def _abort_current(self):
        """Закрываем текущий контейнер/процесс, чтобы декодирование прервалось."""
        container, proc = self._current_container, self._current_proc
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        if container is not None:
            try:
                container.close()
            except Exception:
                pass

    def stop(self):
        self._stop_event.set()
        self._skip_event.set()
        self._abort_current()
        _mixer.stop_music()

    def play(self, query=None):
        if self._thread is not None and self._thread.is_alive():
            self.stop()
            self._thread.join(timeout=5)

        self._query = (query or cfg.music.default_genre or "популярная музыка").strip()
        first = self._search(self._query)
        if not first:
            return False

        self._generation += 1
        self._stop_event.clear()
        self._skip_event.clear()

        with self._lock:
            self._tracks = first
            self._index = 0

        self._thread = threading.Thread(target=self._play_loop, daemon=True)
        self._refill_thread = threading.Thread(target=self._refill_loop, daemon=True)
        self._thread.start()
        self._refill_thread.start()
        return True

    def _refill_loop(self):
        """Фоново догружает очередь, пока играет музыка."""
        generation = self._generation
        while not self._stopped(generation):
            with self._lock:
                remaining = len(self._tracks) - self._index
            if remaining <= MIN_FILL:
                tracks = self._search(self._query)
                if self._stopped(generation):
                    return
                if tracks:
                    self._append_unique(tracks)
            time.sleep(5)

    def _play_loop(self):
        generation = self._generation

        while not self._stopped(generation):
            if self._skip_event.is_set():
                self._skip_event.clear()

            with self._lock:
                if self._index < len(self._tracks):
                    track = dict(self._tracks[self._index])
                    self._index += 1
                else:
                    track = None

            if track is None:
                if not self._wait_for_fill(generation):
                    break
                continue

            log_message(f"Играет: {track['title']}", "music.py")

            _mixer.stop_music()
            try:
                ok = self._play_stream(track['url'], generation)
            except Exception as e:
                log_message(f"Ошибка трека: {e}", "music.py")
                ok = False
            if self._generation != generation:
                return

            if not ok:
                log_message(f"Пропуск: {track['title']}", "music.py")
                continue

            # Ждём, пока трек отыграет (или пропуск/стоп)
            deadline = time.time() + 1800
            while _mixer.music_playing and not self._stopped(generation) and not self._skip_event.is_set():
                if time.time() > deadline:
                    _mixer.stop_music()
                    break
                time.sleep(0.1)

        log_message("Воспроизведение завершено", "music.py")

    def _wait_for_fill(self, generation):
        """Ждём, пока фоновый поток дозагрузит очередь."""
        start = time.time()
        while not self._stopped(generation) and time.time() - start < WAIT_FILL_TIMEOUT:
            with self._lock:
                if self._index < len(self._tracks):
                    return True
            time.sleep(0.2)
        return False

    def next(self):
        if self._thread is None or not self._thread.is_alive():
            return
        self._skip_event.set()
        self._abort_current()
        _mixer.stop_music()

    @property
    def is_playing(self):
        return self._thread is not None and self._thread.is_alive()


_player = MusicPlayer()