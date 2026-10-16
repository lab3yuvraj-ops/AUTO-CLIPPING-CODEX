"""Isolated proxy/section transfers and evidence-based source-time offsets.

Proxy pixels are never eligible final source pixels. Section offsets remain
untrusted until two separated speech windows match the original proxy audio.
Only sanitized records, never extractor URLs, are written to disk.
"""
import math
import subprocess
import json
from contextlib import nullcontext
from pathlib import Path

import numpy as np
from scipy.signal import correlate

from .errors import StageError
from .render import probe, file_hash
from .youtube import ytdlp, transfer_options
from .youtube_transcript import atomic_json


def section_range(start, end, duration, padding=3):
    values = tuple(float(x) for x in (start, end, duration, padding))
    start, end, duration, padding = values
    if not all(math.isfinite(x) for x in values) or not 0 <= start < end <= duration or padding < 0:
        raise ValueError('Section bounds must be finite, ordered and within the original source.')
    return [max(0., start-padding), min(duration, end+padding)]


def _check_info(info):
    if info.get('availability') not in (None, 'public'):
        raise StageError('Fast transfer requires a public source.', False)
    if info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming', 'post_live'):
        raise StageError('Fast transfer requires a completed, processed source.', False)
    if not info.get('duration') or not math.isfinite(float(info['duration'])):
        raise StageError('Fast transfer requires a known source duration.', False)


def _accepted(root, signature):
    path = root/'source.mkv'
    record = root/'accepted.json'
    if not path.is_file() or not record.is_file():
        return None
    import json
    saved = json.loads(record.read_text(encoding='utf-8'))
    if saved.get('signature') == signature and saved.get('source_sha256') == file_hash(path):
        return {**saved, 'source': str(path.resolve()), 'cached': True}
    raise StageError('Existing completed media does not match this transfer request. Use a separate fresh directory.', False)


def _bind_request(root, signature):
    """Never resume another video's partial or a different passage in place."""
    import json
    marker = root/'transfer-request.json'
    if marker.is_file():
        if json.loads(marker.read_text(encoding='utf-8')) != signature:
            raise StageError('This transfer folder belongs to a different source/range. Preserve its partials and use a separate directory.', False)
    elif any(root.glob('source.*')):
        raise StageError('Unidentified existing media cannot be reused for a fresh proxy/section transfer.', False)
    atomic_json(marker, signature)


def _media(path):
    if not path.is_file():
        raise StageError('Transfer did not produce a complete section file; partials remain available for resuming.')
    data = probe(path)
    video = next((s for s in data['streams'] if s.get('codec_type') == 'video'), {})
    audio = next((s for s in data['streams'] if s.get('codec_type') == 'audio'), {})
    duration = float(data['format'].get('duration', 0))
    if not video or not audio or not math.isfinite(duration) or duration <= 0:
        raise StageError('Completed transfer lacks valid video/audio/duration; no media was accepted.', False)
    if abs(float(video.get('start_time', 0))-float(audio.get('start_time', 0))) > .08:
        raise StageError('Transferred section has inconsistent audio/video stream starts; do not trust proxy offsets.', False)
    return video, audio, duration


def download_proxy(info, root,on_audio_ready=None):
    """Download whole-source <=480p editorial proxy plus best available audio."""
    _check_info(info)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    signature = {'version': 1, 'kind': 'proxy', 'video_id': info['id'], 'duration': float(info['duration']), 'height_limit': 480}
    cached = _accepted(root, signature)
    if cached:
        if on_audio_ready:on_audio_ready(cached['source'])
        return cached
    _bind_request(root, signature)
    # Native/aria2 policy remains shared with the normal downloader, including
    # preservation of the backend for existing sparse partials.
    options={'on_audio_ready':on_audio_ready} if on_audio_ready else {}
    ytdlp([*transfer_options(root), '-f', 'ba+bv[height<=480]/b[height<=480]',
           '--merge-output-format', 'mkv', '--remux-video', 'mkv', '--continue',
           '--abort-on-unavailable-fragments', '--max-filesize', '12G',
           '-o', str(root/'source.%(ext)s')], timeout=900, info=info, progress_root=root,**options)
    path = root/'source.mkv'
    video, _, duration = _media(path)
    if video.get('height', 0) > 480 or abs(duration-float(info['duration'])) > 2:
        raise StageError('Proxy failed its resolution/duration checks. It is not an accepted original source.', False)
    result = {'source': str(path.resolve()), 'source_sha256': file_hash(path), 'height': video['height'],
              'duration': duration, 'source_offset': 0., 'offset_verified': False,
              'kind': 'proxy', 'render_eligible': False, 'cached': False, 'signature': signature}
    atomic_json(root/'accepted.json', result)
    return result


def download_section(info, root, start, end, source_duration, padding=3, *, lossless_cut=False):
    """Transfer highest advertised quality for a padded original-source range.

    Copy-mode section seeking can retain keyframe pre-roll. The returned
    source_offset is a tentative search position, never trusted render timing.
    """
    _check_info(info)
    if abs(float(source_duration)-float(info['duration'])) > 2:
        raise StageError('Section source duration disagrees with resolved metadata.', False)
    bounds = section_range(start, end, source_duration, padding)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    height = max((f.get('height') or 0 for f in info.get('formats', []) if f.get('vcodec') not in (None, 'none')), default=0)
    if not height:
        raise StageError('No advertised original video quality is available.', False)
    signature = {'version': 1, 'kind': 'section', 'video_id': info['id'],
                 'requested_range': [float(start), float(end)], 'padded_range': bounds, 'highest_height': height}
    if lossless_cut:signature['lossless_exact_cut']=True
    cached = _accepted(root, signature)
    if cached:
        return cached
    _bind_request(root, signature)
    options=[x.replace('--max-tries=2','--max-tries=1') for x in transfer_options(root)]
    # yt-dlp's socket timeout does not bound FFmpeg's separate network inputs.
    # Apply to EVERY input (video and audio), without reconnect/retry loops.
    # FFmpeg 8.1 can inherit a negative short-seek capability which its HTTP
    # unsigned comparison treats as permission to drain the remaining file.
    # A positive 1-byte threshold forces range seeks instead of whole-stream
    # readahead; this changes transport only, never source pixels or encoding.
    cut_options=['--force-keyframes-at-cuts','--downloader-args','ffmpeg_o:-c:v libx264 -preset ultrafast -crf 0 -c:a flac'] if lossless_cut else []
    ytdlp([*options, '--downloader-args','ffmpeg_i:-rw_timeout 15000000 -short_seek_size 1',*cut_options,
           '--retries','0','--fragment-retries','0','--extractor-retries','0','-f', 'bv*+ba/b', '--download-sections', f'*{bounds[0]:.6f}-{bounds[1]:.6f}',
           '--merge-output-format', 'mkv', '--remux-video', 'mkv', '--continue',
           '--abort-on-unavailable-fragments', '--max-filesize', '12G',
           '-o', str(root/'source.%(ext)s')], timeout=900, info=info, progress_root=root)
    path = root/'source.mkv'
    try:video, _, duration = _media(path)
    except StageError as exc:
        if lossless_cut or 'inconsistent audio/video stream starts' not in str(exc):raise
        atomic_json(root/'alignment-fallback.json',{'cause':str(exc),'route':'one lossless exact-cut selected-section recovery',
            'video_encoding':'libx264 CRF 0 ultrafast','audio_encoding':'FLAC','full_video_fallback':False,
            'original_section_preserved':True})
        return download_section(info,root/'aligned-lossless',start,end,source_duration,padding,lossless_cut=True)
    expected = bounds[1]-bounds[0]
    # A small keyframe lead/trail is allowed for measurement, not guessed away.
    if video.get('height', 0) < height or duration < expected-.15 or duration > expected+10:
        raise StageError('Section is incomplete, outside its bounded pre-roll budget or below highest advertised quality.', False)
    result = {'source': str(path.resolve()), 'source_sha256': file_hash(path), 'height': video['height'],
              'duration': duration, 'requested_range': [float(start), float(end)], 'padded_range': bounds,
              'source_offset': bounds[0], 'offset_verified': False, 'kind': 'section',
              'render_eligible': False, 'cached': False, 'signature': signature}
    if lossless_cut:result['preparation_encoding']={'video':'lossless libx264 CRF 0','audio':'lossless FLAC','reason':'copy-mode keyframe seek produced mismatched stream starts'}
    atomic_json(root/'accepted.json', result)
    return result


def sections_or_full(info,root,ranges,duration,full_download,timing_hook=None):
    """One section attempt per selected range, one full fallback, no retry loop."""
    root=Path(root);padded=[section_range(a,b,duration) for a,b in ranges]
    try:
        with timing_hook('section_download') if timing_hook else nullcontext():
            return [download_section(info,root/'sections'/f'clip-{i+1}',a,b,duration) for i,(a,b) in enumerate(ranges)]
    except StageError as exc:
        from .caption_errors import classify_caption_failure
        cause=classify_caption_failure(str(exc))
        atomic_json(root/'section-fallback.json',{'cause':cause,'section_attempts_per_range':1,'full_fallback_attempts':1,'reason':'Section transfer failed; one highest-quality full download is attempted immediately, concurrently with speech verification.'})
        print('Section download failed; attempting one full-quality download. See section-fallback.json.',flush=True)
        with timing_hook('full_download_fallback') if timing_hook else nullcontext():full=full_download()
        source=full['source'];height=next(s['height'] for s in probe(source)['streams'] if s['codec_type']=='video')
        return [{'source':source,'source_sha256':file_hash(source),'source_offset':0,'kind':'full','height':height,'offset_verified':False,'padded_range':bounds,'cached':bool(full.get('cached',False))} for bounds in padded]


def _audio(path, start, duration, sample_rate=8000):
    result = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{max(0.,start):.6f}', '-i', str(path),
                             '-t', f'{duration:.6f}', '-vn', '-ac', '1', '-ar', str(sample_rate),
                             '-f', 'f32le', 'pipe:1'], capture_output=True, timeout=60)
    if result.returncode:
        raise StageError('Unable to decode section anchor audio; proxy timings are not trusted.', False)
    return np.frombuffer(result.stdout, dtype='<f4').astype(np.float64)


def _match_audio(reference, search, sample_rate=8000):
    """Normalized cross-correlation with silence/ambiguous-match rejection."""
    reference = np.asarray(reference, dtype=np.float64)
    search = np.asarray(search, dtype=np.float64)
    n = len(reference)
    if n < sample_rate//4 or len(search) < n:
        return {'accepted': False, 'reason': 'insufficient_anchor_audio'}
    reference = reference-reference.mean()
    energy = float(np.dot(reference, reference))
    if energy/n < 1e-8:
        return {'accepted': False, 'reason': 'silent_anchor_audio'}
    sums = np.concatenate(([0.], np.cumsum(search)))
    squares = np.concatenate(([0.], np.cumsum(search*search)))
    window_energy = squares[n:]-squares[:-n]-(sums[n:]-sums[:-n])**2/n
    scores = correlate(search, reference, mode='valid', method='fft')/np.sqrt(np.maximum(window_energy*energy, 1e-20))
    peak = int(np.argmax(scores))
    confidence = float(scores[peak])
    remaining = scores.copy()
    exclusion = int(sample_rate*.12)
    remaining[max(0,peak-exclusion):min(len(scores),peak+exclusion+1)] = -1
    second = float(np.max(remaining))
    accepted = confidence >= .75 and confidence-second >= .04
    return {'accepted': bool(accepted), 'position_seconds': peak/sample_rate,
            'confidence': confidence, 'distinctness': confidence-second,
            'reason': None if accepted else 'weak_or_ambiguous_audio_match'}


def confirm_section_audio(proxy, section, padded_range, words, tolerance=.08):
    """Confirm two distant source-word audio anchors against downloaded audio.

    A rejection explicitly requires verified section audio; it never blesses
    the requested start as an actual offset. Only accepted reports expose a
    measured source_offset. ``words`` must already be local verified words.
    """
    start, end = map(float, padded_range)
    if not 0 < float(tolerance) <= .08 or not 0 <= start < end:
        raise ValueError('Audio offset tolerance must be positive and no more than 80ms.')
    usable = sorted((w for w in words if start+.6 <= float(w['start']) and float(w['end']) <= end-.6), key=lambda w: w['start'])
    report = {'route': 'proxy_anchor_check', 'offset_verified': False, 'verify_section_required': True,
              'tolerance_seconds': float(tolerance), 'anchors': []}
    report_path = Path(section).parent/'audio-offset-check.json'
    if len(usable) < 2 or float(usable[-1]['start'])-float(usable[0]['start']) < min(10., (end-start)*.5):
        report['reason'] = 'insufficient_separated_verified_word_anchors'
        atomic_json(report_path, report)
        return report
    for word in (usable[0], usable[-1]):
        anchor_start = max(start, float(word['start'])-.4)
        reference = _audio(proxy, anchor_start, 1.4)
        predicted = anchor_start-start
        search_start = max(0., predicted-5.)
        search = _audio(section, search_start, 11.4)
        match = _match_audio(reference, search)
        item = {'word_id': word.get('id'), 'source_word_start': float(word['start']),
                'source_anchor_start': anchor_start, **match}
        if match['accepted']:
            item['measured_source_offset'] = anchor_start-(search_start+match['position_seconds'])
        report['anchors'].append(item)
    if all(a['accepted'] for a in report['anchors']):
        offsets = [a['measured_source_offset'] for a in report['anchors']]
        drift = abs(offsets[1]-offsets[0])
        report['drift_seconds'] = drift
        # Confirm the proxy's direct source-time mapping, not merely a stable
        # shifted match; mismatched seek offsets require section verification.
        if drift <= tolerance and all(abs(offset-start) <= tolerance for offset in offsets):
            report.update(offset_verified=True, verify_section_required=False,
                          source_offset=sum(offsets)/len(offsets), route='proxy_verified_against_section')
        else:
            report['reason'] = 'section_seek_offset_or_audio_drift_exceeds_tolerance'
    else:
        report['reason'] = 'anchor_audio_not_reliably_matched'
    atomic_json(report_path, report)
    return report
