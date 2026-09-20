"""
Transcript extraction for the video-import endpoint.

Two stages, tried in order:

1. **Captions** — pure-Python ``yt-dlp`` downloads the uploader's (auto)
   subtitle track and it is parsed to plain text. Works in the alpine
   (musl) container: no native wheels required.
2. **Whisper** — if no usable caption track is present, the audio is
   downloaded and transcribed with ``faster-whisper``. ``faster-whisper``
   depends on ``ctranslate2``, which has no musl build, so on the alpine
   image this stage degrades to a clear error instead of a hard crash. It
   runs unchanged on a glibc host where the package is installed.

The module has no import-time third-party dependency: ``yt_dlp`` and
``faster_whisper`` are imported lazily inside the functions that need them,
so the plugin loads (and the caption path works) even with neither present.
"""

import glob
import os
import re

# A caption track shorter than this is treated as unusable and falls through
# to the Whisper stage instead of being returned.
MIN_TRANSCRIPT_WORDS = 25
CAPTION_LANGS = ('en', 'en-US', 'en-GB', 'en-orig', 'orig')
CAPTION_EXTS = ('vtt', 'srt', 'srv1', 'srv2', 'srv3')
AUDIO_EXTS = ('m4a', 'mp3', 'webm', 'opus', 'wav', 'flac', 'aac', 'ogg')


class TranscriptError(Exception):
    """Raised when no usable transcript could be produced for a URL."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def get_transcript(url, language='en'):
    """
    Return a transcript for the video at ``url``.

    :return: dict with keys ``text`` (str), ``method`` (``'captions'`` or
        ``'whisper'``), ``title`` (str), ``duration`` (seconds or ``None``)
        and ``image_url`` (thumbnail URL or ``None``).
    :raises TranscriptError: if neither stage yields a usable transcript.
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix='import_web_stt_') as tmpdir:
        info = _fetch_metadata_and_captions(url, tmpdir)

        text = ''
        method = 'captions'
        caption_file = _find_file(tmpdir, 'subs', CAPTION_EXTS)
        if caption_file:
            text = caption_to_text(caption_file)

        used_whisper = False
        if len(text.split()) < MIN_TRANSCRIPT_WORDS:
            audio_file = _download_audio(url, tmpdir)
            text = whisper_transcribe(audio_file, language=language)
            method = 'whisper'
            used_whisper = True

        if not text or len(text.split()) < MIN_TRANSCRIPT_WORDS:
            raise TranscriptError(
                'No usable transcript could be obtained from '
                f'{url!r} — the video has no caption track and speech-to-text '
                'was unavailable.'
            )

        title = (info or {}).get('title') or ''
        return {
            'text': text,
            'method': method,
            'title': title,
            'duration': (info or {}).get('duration'),
            'image_url': (info or {}).get('thumbnail') or None,
            'title_used': not used_whisper,
        }


def caption_to_text(path):
    """Parse a VTT/SRT caption file into a single reflowed paragraph of text."""
    lines = []
    with open(path, encoding='utf-8-sig') as handle:
        for raw in handle.read().splitlines():
            line = raw.strip()
            if not line:
                continue
            if '-->' in line:
                continue
            if line.isdigit():
                continue
            if line == 'WEBVTT' or line.startswith('Kind:') or line.startswith('Language:'):
                continue
            lines.append(line)

    out = []
    for line in lines:
        if out and out[-1].strip() == line.strip():
            continue
        out.append(line)

    return re.sub(r'\s+', ' ', ' '.join(out)).strip()


def _import_yt_dlp():
    try:
        import yt_dlp
    except Exception as exc:  # noqa: BLE001 - surfaced as a user-facing error
        raise TranscriptError(
            'yt-dlp is not installed, which is required to read video '
            'captions/audio. Install it (pip install yt-dlp) to enable the '
            'video import path.'
        ) from exc
    return yt_dlp


def _fetch_metadata_and_captions(url, tmpdir):
    yt_dlp = _import_yt_dlp()
    options = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': list(CAPTION_LANGS),
        'subtitlesformat': 'vtt',
        'outtmpl': os.path.join(tmpdir, 'subs'),
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:  # noqa: BLE001 - network/URL problems
        raise TranscriptError(f'Could not reach the video at {url!r}: {exc}') from exc

    info = info or {}
    if info.get('_type') in ('playlist', 'multi_video'):
        entries = info.get('entries') or []
        info = entries[0] if entries else {}
    return info


def _download_audio(url, tmpdir):
    yt_dlp = _import_yt_dlp()
    options = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(tmpdir, 'audio'),
        'skip_download': False,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.extract_info(url, download=True)
    except Exception as exc:  # noqa: BLE001 - network/download problems
        raise TranscriptError(
            f'Could not download audio from {url!r} for speech-to-text: {exc}'
        ) from exc

    audio_file = _find_file(tmpdir, 'audio', AUDIO_EXTS)
    if not audio_file:
        audio_file = _find_file(tmpdir, 'audio', None)
    if not audio_file:
        raise TranscriptError('Audio was downloaded but the audio file could not be located.')
    return audio_file


def whisper_transcribe(audio_path, language='en'):
    """Transcribe an audio file with ``faster-whisper`` (CPU, int8)."""
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # noqa: BLE001 - ImportError / no musl wheel
        raise TranscriptError(
            'Speech-to-text is not available in this environment: the '
            '"faster-whisper" package (Whisper fallback) is not installed. '
            'Provide a transcript directly, or run with the Whisper backend '
            'enabled.'
        ) from exc

    model = WhisperModel('small', device='cpu', compute_type='int8')
    segments, _info = model.transcribe(audio_path, language=language, vad_filter=True, beam_size=5)
    parts = [seg.text.strip() for seg in segments if str(seg.text).strip()]
    return re.sub(r'\s+', ' ', ' '.join(parts)).strip()


def _find_file(tmpdir, stem, exts):
    for ext in (exts or ('',)):
        for path in sorted(glob.glob(os.path.join(tmpdir, f'{stem}*.{ext}'))):
            return path
    return None
