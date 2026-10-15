"""Bounded six-frame feasibility gate; no gate ASR or diarization inference.

CPU face boxes are proposals, never speaker identities. Actual sampled pixels
require explicit Codex review. Selected-passage speaker work happens later.
"""
import concurrent.futures
import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import cv2
from PIL import Image, ImageDraw

from .config import ROOT
from .errors import StageError
from .render import file_hash, probe
from .youtube_transcript import atomic_json


def sample_times(duration):
    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Visual feasibility sampling requires a finite source duration.')
    # Six frames is the hard cap, irrespective of source length.
    return [(i+.5)*duration/6 for i in range(6)]


def _sample_format(info):
    candidates = [item for item in info.get('formats', [])
                  if item.get('vcodec') not in (None, 'none') and 0 < (item.get('height') or 0) <= 480
                  and urlparse(item.get('url', '')).scheme == 'https']
    if not candidates:
        raise StageError('No <=480p stream is available for the bounded visual gate.', False)
    return max(candidates, key=lambda item: (item.get('height') or 0, item.get('fps') or 0, item.get('tbr') or 0))


def _seek_frame(fmt, timestamp, path):
    args = ['ffmpeg', '-hide_banner', '-loglevel', 'info', '-y', '-hwaccel', 'none']
    trust = ROOT/'.venv/ca.pem'
    if urlparse(fmt['url']).scheme == 'https':
        args += ['-rw_timeout', '15000000', '-tls_verify', '1']
        if trust.is_file():
            args += ['-ca_file', str(trust)]
    # Header values and signed URL stay exclusively in process memory. Neither
    # arguments nor raw FFmpeg stderr are persisted or sent to the console.
    headers = fmt.get('http_headers') or {}
    if headers:
        safe = {key: value for key, value in headers.items()
                if '\r' not in str(key)+str(value) and '\n' not in str(key)+str(value)}
        if safe:
            args += ['-headers', ''.join(f'{key}: {value}\r\n' for key, value in safe.items())]
    args += ['-copyts', '-ss', f'{timestamp:.6f}', '-i', fmt['url'], '-an', '-frames:v', '1',
             '-vf', 'scale=640:-2,showinfo', '-fps_mode', 'vfr', str(path)]
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=35)
    except subprocess.TimeoutExpired as error:
        raise StageError('A visual gate frame seek exceeded its 35-second budget. No signed URL was logged.', False) from None
    if result.returncode or not path.is_file():
        code = ' (HTTP 429)' if re.search(r'\b429\b', result.stderr) else ' (HTTP 403)' if re.search(r'\b403\b', result.stderr) else ''
        raise StageError('YouTube visual gate frame seek failed'+code+'. No source pixels were accepted.', False)
    stamps = [float(value) for value in re.findall(r'\bn:\s*0\b.*?\bpts_time:([\d.eE+-]+)', result.stderr)]
    if not stamps or not math.isfinite(stamps[0]) or abs(stamps[0]-timestamp) > 2:
        raise StageError('Visual gate frame source timestamp could not be established. No inferred timestamp was accepted.', False)
    return stamps[0]


def _faces(path):
    image = cv2.imread(str(path))
    if image is None:
        raise StageError('Visual gate frame could not be read.', False)
    detector = cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
    if detector.empty():
        raise StageError('Local CPU face proposal detector is unavailable; no model download was attempted.', False)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    boxes = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(24,24))
    height, width = image.shape[:2]
    return [{'x':int(x), 'y':int(y), 'width':int(w), 'height':int(h),
             'normalized_box':[x/width,y/height,(x+w)/width,(y+h)/height]} for x,y,w,h in boxes]


def gather_visual_samples(info, root, local_proxy=None):
    """Decode six bounded frames remotely or from an already accepted proxy.

    The orchestrator may wait for its *existing* proxy future after a remote
    HTTP403, then pass that complete file here. This function never downloads
    again and never attempts to decode growing partial media.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    times = sample_times(info['duration'])
    route = 'remote_stream'
    proxy_hash = None
    if local_proxy is None:
        fmt = _sample_format(info)
    else:
        local_proxy = Path(local_proxy.get('source') if isinstance(local_proxy,dict) else local_proxy)
        if not local_proxy.is_file() or local_proxy.suffix in ('.part','.aria2'):
            raise StageError('Local visual sampling requires a complete accepted proxy, never a partial stream.', False)
        media = probe(local_proxy)
        video = next((s for s in media['streams'] if s.get('codec_type') == 'video'), {})
        audio = next((s for s in media['streams'] if s.get('codec_type') == 'audio'), {})
        if not video or not audio or not 0 < video.get('height',0) <= 480 or abs(float(media['format'].get('duration',0))-float(info['duration'])) > 2:
            raise StageError('Local visual sampling proxy failed complete audio/resolution/duration checks.', False)
        proxy_hash = file_hash(local_proxy)
        fmt = {'url':str(local_proxy.resolve()),'format_id':'accepted-local-proxy'}
        route = 'local_proxy_after_remote403'
    signature = {'version':2, 'source_id':info['id'], 'duration':float(info['duration']),
                 'requested_times':times, 'sample_format_id':str(fmt.get('format_id')),
                 'maximum_frames':6, 'face_detector':'OpenCV CPU Haar proposals',
                 'route':route,'local_proxy_sha256':proxy_hash}
    saved_path = root/'visual-samples.json'
    if saved_path.is_file():
        saved = json.loads(saved_path.read_text(encoding='utf-8'))
        if saved.get('signature') == signature and len(saved.get('frames', [])) == 6 and len(saved.get('page_files', [])) == 1 and all(Path(item['file']).is_file() and file_hash(item['file']) == item['sha256']
                                                        for item in saved.get('frames', [])+saved.get('page_files', [])):
            return {**saved, 'cached':True}
        raise StageError('Existing visual gate samples changed or belong to another source. Use a fresh sampling folder.', False)
    started = time.perf_counter()
    def extract(item):
        index, requested = item
        path = root/f'frame-{index+1:02d}.jpg'
        stamp = _seek_frame(fmt, requested, path)
        return {'file':str(path.resolve()), 'sha256':file_hash(path),
                'source_seconds':stamp, 'requested_seconds':requested, 'face_proposals':_faces(path)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(extract, item):item[0] for item in enumerate(times)}
        ordered = {}
        try:
            for future in concurrent.futures.as_completed(futures):
                ordered[futures[future]] = future.result()
        except Exception:
            # Do not start queued seeks after an authorization/rate-limit error.
            # At most one already running peer seek finishes within its budget.
            for future in futures:
                future.cancel()
            raise
        frames = [ordered[index] for index in range(len(times))]
    sheet = Image.new('RGB', (1280,3*388), '#171b19')
    draw = ImageDraw.Draw(sheet)
    for i, frame in enumerate(frames):
        x, y = (i%2)*640, (i//2)*388
        with Image.open(frame['file']) as image:
            image.thumbnail((632,356))
            sheet.paste(image, (x+4,y+26))
        draw.text((x+8,y+5), f"Source {frame['source_seconds']:.3f}s; CPU face proposals {len(frame['face_proposals'])}", fill='white')
    page = root/'visual-feasibility.jpg'
    sheet.save(page, quality=94)
    page_files = [{'file':str(page.resolve()), 'sha256':file_hash(page)}]
    sample_hashes = {frame['file']:frame['sha256'] for frame in frames}
    fingerprint = hashlib.sha256(json.dumps({'source_id':info['id'],'samples':sample_hashes},sort_keys=True).encode()).hexdigest()
    report = {'source_id':info['id'], 'signature':signature, 'frames':frames,
              'pages':[item['file'] for item in page_files], 'pagefiles':[item['file'] for item in page_files],
              'page_files':page_files, 'overview_hashes':{item['file']:item['sha256'] for item in page_files},
              'samplehashes':sample_hashes, 'visual_samples_sha256':fingerprint,
              'source_seconds':float(info['duration']), 'seconds':time.perf_counter()-started, 'cached':False,
              'route':route, 'sampling_seconds':time.perf_counter()-started,
              'local_proxy_sha256':proxy_hash,
              'overlap_note':'Sampling began only after the completed proxy was available; any earlier proxy wait is recorded by the enclosing stage.' if local_proxy is not None else 'Remote frame seeks can overlap the separate proxy download.',
              'note':'Six actual frames only. CPU face proposals do not identify speakers or prove reliable tracking; explicit Codex feasibility review is required.'}
    atomic_json(saved_path, report)
    return report


def evaluate_gate(captions_complete, audio_report, visual_evidence, proxy_sha256, overview_hashes):
    """Pure feasibility checks; legacy audio dominance evidence is not used.

    ``proxy_sha256`` can be the hash of the bounded visual sample set before a
    full proxy exists. Evidence must bind ``visual_samples_sha256`` in that case.
    """
    checks = {}
    def check(name, passed, reason, pending=False):
        checks[name] = {'passed':bool(passed), 'status':'passed' if passed else 'pending' if pending else 'failed', 'reason':None if passed else reason}
    # Caption availability and source-wide speaker count are not eligibility
    # checks. The caller must rank and explicitly classify a selected passage.
    visual = visual_evidence or {}
    missing = not visual_evidence
    binding = visual.get('visual_samples_sha256') or visual.get('proxy_sha256')
    check('visual_hash', bool(proxy_sha256) and binding == proxy_sha256, 'Visual review is absent or belongs to different actual samples.', missing)
    check('overview_pages', bool(overview_hashes) and visual.get('overview_hashes') == overview_hashes, 'Actual sample page hashes were not reviewed or changed.', missing)
    evidence = visual.get('evidence')
    has_evidence = bool(evidence.strip()) if isinstance(evidence,str) else isinstance(evidence,list) and bool(evidence) and all(isinstance(x,str) and x.strip() for x in evidence)
    check('explicit_review', visual.get('reviewed_by') == 'Codex' and has_evidence, 'Explicit Codex feasibility review is required; face proposals are not identity evidence.', missing)
    check('live_action', visual.get('live_action') is True and visual.get('animated') is False, 'Animated or uncertain identity-tracking footage is not eligible.', missing)
    count = visual.get('speaker_count')
    check('passage_classification',visual.get('classification') in ('single/dominant-presenter','multi-speaker dialogue'),'A selected passage must be explicitly classified; source-wide speaker counts are insufficient.',missing)
    strategy = visual.get('chosen_strategy') or visual.get('strategy')
    check('tracking_strategy', strategy in ('fixed','face-tracked','speaker-switching'), 'Choose an explicitly reviewed fixed, face-tracked or speaker-switching strategy.', missing)
    confidence = visual.get('confidence')
    stable=visual.get('faces_reliable') is not True or visual.get('speakers_reliable') is not True or not isinstance(confidence,(int,float)) or confidence<.8
    failures = [name for name,item in checks.items() if item['status'] == 'failed']
    pending = [name for name,item in checks.items() if item['status'] == 'pending']
    return {'eligible':not failures and not pending, 'status':'rejected' if failures else 'pending' if pending else 'eligible',
            'chosen_strategy':strategy if not failures and not pending else None,
            'speaker_count':count, 'reasons':[item['reason'] for item in checks.values() if not item['passed']],
            'requires_stable_context':stable,'editorial_warnings':['Hold reviewed stable context crop; identity requires human review.'] if stable else [],
            'failed_checks':failures, 'pending_checks':pending, 'checks':checks,
            'limitations':'Six-frame feasibility sampling does not prove whole-source continuous tracking; selected passages still require actual identity/crop review.'}
