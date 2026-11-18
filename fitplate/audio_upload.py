"""Normalize mobile recording containers before speech recognition."""
import io
from pathlib import Path
import subprocess
import tempfile
import wave

AUDIO_SUFFIXES = {'.wav','.mp3','.m4a','.mp4','.aac','.webm','.weba','.ogg','.oga','.opus','.caf','.aif','.aiff','.amr','.3gp','.flac'}


def normalize_mobile_audio(data, filename):
    if Path(filename).suffix.lower() in {'.wav','.mp3'}:
        return data, filename
    from imageio_ffmpeg import get_ffmpeg_exe
    with tempfile.TemporaryDirectory(prefix='fitplate-audio-') as directory:
        source=Path(directory)/'recording'; output=Path(directory)/'normalized.wav'
        source.write_bytes(data)
        try:
            run=subprocess.run([get_ffmpeg_exe(),'-nostdin','-v','error','-threads','1',
                '-protocol_whitelist','file,pipe','-i',str(source),'-map','0:a:0','-vn',
                '-t','61','-ac','1','-ar','16000','-c:a','pcm_s16le',str(output)],
                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=25,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if run.returncode or not output.exists():
                raise ValueError()
            result=output.read_bytes()
            with wave.open(io.BytesIO(result)) as audio:
                if not 0 < audio.getnframes()/audio.getframerate() <= 60:
                    raise ValueError()
            return result,'recording.wav'
        except (OSError,subprocess.TimeoutExpired,ValueError,wave.Error,EOFError):
            raise ValueError('This recording could not be decoded. Use an audio recording of up to 60 seconds.') from None
