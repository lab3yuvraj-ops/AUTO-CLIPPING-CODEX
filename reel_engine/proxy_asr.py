"""Bind early complete audio ASR to proxy pixels only on exact audio evidence."""
from pathlib import Path
import hashlib
import json
import soundfile
from .render import file_hash,run
from .local_transcription import transcribe_local
from .youtube_transcript import atomic_json


def pcm_hash(path):
    digest=hashlib.sha256()
    with soundfile.SoundFile(path) as audio:
        if audio.samplerate!=16000 or audio.channels!=1:raise ValueError('ASR audio must be mono 16kHz.')
        for block in audio.blocks(blocksize=65536,dtype='int16'):digest.update(block.tobytes())
    return digest.hexdigest()


def bind_proxy_asr(audio_source,asr_root,proxy,root,transcribe=None):
    root=Path(root);asr_root=Path(asr_root)
    data=json.loads((asr_root/'transcript.json').read_text(encoding='utf-8'))
    proxy_audio=root/'local-audio.wav'
    run(['ffmpeg','-v','error','-y','-i',proxy['source'],'-vn','-ar','16000','-ac','1','-c:a','pcm_s16le',str(proxy_audio)])
    identical=pcm_hash(proxy_audio)==pcm_hash(asr_root/'local-audio.wav')
    if not identical:
        # No inferred audio offset is silently applied to the full editorial draft.
        fallback=root/'proxy-asr-recovery';fallback.mkdir(exist_ok=True)
        (transcribe or transcribe_local)(proxy['source'],fallback)
        data=json.loads((fallback/'transcript.json').read_text(encoding='utf-8'))
    else:
        data['asr_original_source_sha256']=data['source_sha256']
        data['source_sha256']=proxy['source_sha256']
    data['asr_audio_source']=str(Path(audio_source).resolve()) if identical else proxy['source']
    data['audio_equivalence']={'identical_pcm':identical,'proxy_pcm_sha256':pcm_hash(proxy_audio),'route':'exact-mono16k-pcm' if identical else 'fresh-proxy-ASR'}
    data.setdefault('models',{})['compute_type']='int8'
    atomic_json(root/'transcript.json',data)
    atomic_json(root/'audio-equivalence.json',data['audio_equivalence'])
    return data
