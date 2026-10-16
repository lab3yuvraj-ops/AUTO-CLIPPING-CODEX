"""Delete only generated media in a completed YouTube job family.

Keep final exports and all JSON/text evidence. Never traverse links, remove a
directory recursively, clean another job's referenced media, or purge global
package/model caches. Missing working media is explicit, not fake resumability.
"""
import hashlib
import json
import os
import re
import time
import threading
from pathlib import Path
from .youtube_transcript import atomic_json

MEDIA = {'.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4v', '.wav', '.mp3',
         '.flac', '.aac', '.m4a', '.opus', '.ogg', '.png', '.jpg', '.jpeg',
         '.gif', '.npy', '.npz', '.part', '.ytdl', '.aria2'}
_LOCK = threading.Lock()


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _safe(path, root):
    """Validate lexical containment AND every existing ancestor before unlink."""
    path = Path(os.path.abspath(path)); root = Path(root).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError('Cleanup target is outside its private job/cache directory.')
    for p in [path, *path.parents]:
        if p == root.parent:
            break
        if p.is_symlink() or (p.exists() and getattr(p.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Cleanup refuses symlinks or Windows reparse points.')
    if not path.resolve().is_relative_to(root):
        raise ValueError('Cleanup target resolves outside its private directory.')
    return path


def _references(value):
    if isinstance(value, str):
        p = Path(value)
        if p.is_absolute():
            yield p.resolve()
    elif isinstance(value, dict):
        for v in value.values():
            yield from _references(v)
    elif isinstance(value, list):
        for v in value:
            yield from _references(v)


def _files(root):
    # Do not enter junctions, including an apparently empty directory junction.
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            _safe(Path(folder)/name, root)
        for name in files:
            yield _safe(Path(folder)/name, root)


def cleanup_completed(state, ident, *, protected_paths=()):
    # render-batch can finish siblings in separate threads. CLI locking covers
    # separate processes; this covers its bounded in-process worker pool.
    with _LOCK:
        return _cleanup_completed(state, ident, protected_paths=protected_paths)


def _cleanup_completed(state, ident, *, protected_paths=()):
    state = Path(state).resolve(); jobs = state/'jobs'
    if not re.fullmatch(r'[A-Za-z0-9_-]{11,64}', ident):
        raise ValueError('Invalid cleanup job ID.')
    requested = _read(_safe(jobs/ident/'job.json', jobs))
    parent_id = requested.get('source_job_id', ident)
    if not re.fullmatch(r'[A-Za-z0-9_-]{11,64}', parent_id):
        raise ValueError('Invalid parent cleanup job ID.')
    parent_dir = _safe(jobs/parent_id, jobs)
    parent = _read(parent_dir/'job.json')
    def deferred(reason):
        return {'completed': False, 'reason': reason, 'deleted_bytes': 0}
    if not parent.get('transcript_first') or not parent.get('video_id'):
        return deferred('Only app-owned transcript-first YouTube job media is cleaned automatically.')
    entries = parent.get('clips', [])
    if not entries:
        return deferred('Selection/preparation has not completed.')
    records = [(parent_dir, parent)]; exports = set()
    for entry in entries:
        child_id = entry['id']
        if not re.fullmatch(r'[A-Za-z0-9_-]{11,64}', child_id):
            raise ValueError('Invalid child cleanup job ID.')
        folder = _safe(jobs/child_id, jobs); child = _read(folder/'job.json')
        if child.get('source_job_id') != parent_id:
            raise ValueError('Child job does not belong to this source.')
        if child.get('status') not in ('Needs approval', 'Published'):
            return deferred('Wait for every selected clip to finish; failed/active/publishing jobs retain their work.')
        if child.get('publishing') and not child.get('post_id'):
            return deferred('Pending publication must be reconciled before cleanup.')
        if child.get('keep_lossless'):
            return deferred('Explicit keep-lossless retention is enabled.')
        if not child.get('checks') or any(c.get('status') == 'fail' for c in child['checks']):
            return deferred('Technical checks have not passed for every clip.')
        if child.get('review_mode') != 'single-pass' and child.get('status') != 'Published':
            return deferred('Legacy final inspection/publication is still pending.')
        video = Path(child.get('video', ''))
        if not video.is_absolute() or not video.is_file():
            return deferred('A final MP4 is missing.')
        with video.open('rb') as stream:
            fingerprint = hashlib.file_digest(stream, 'sha256').hexdigest()
        if fingerprint != child.get('render_sha256'):
            return deferred('A final MP4 no longer matches its validated hash.')
        exports.add(video.resolve()); records.append((folder, child))
    # Keep any generated media referenced by another job or by shared defaults,
    # reference records, the configured models/cookies, or the final exports.
    protected = set(exports) | {Path(p).resolve() for p in protected_paths if p}
    own = {folder.name for folder, _ in records}
    for record in jobs.glob('*/job.json'):
        if record.parent.name not in own:
            protected.update(_references(_read(record)))
    for name in ('approved-reference.json', 'output-defaults.json'):
        if (state/name).is_file():
            protected.update(_references(_read(state/name)))
    targets = []
    for folder, _ in records:
        for p in _files(folder):
            if p.suffix.lower() not in MEDIA:
                continue
            resolved = p.resolve()
            if any(resolved == q or resolved.is_relative_to(q) for q in protected):
                continue
            targets.append(p)
    # Fully validate the plan before the first deletion; log success per file.
    receipt_path = parent_dir/'storage-cleanup.json'
    receipt = _read(receipt_path) if receipt_path.exists() else {'deleted_bytes': 0, 'deleted_files': []}
    receipt.update(completed=False, started=time.time(), final_exports_preserved=True,
                   note='Working media removed; a later revision must reacquire source media. Verified words/specs/timings and publication state remain.')
    atomic_json(receipt_path, receipt)
    try:
        for p in targets:
            _safe(p, jobs)
            if p.exists():
                count = p.stat().st_size
                p.unlink()
                receipt['deleted_bytes'] += count
                receipt['deleted_files'].append(str(p.relative_to(jobs)))
                atomic_json(receipt_path, receipt)
        receipt.update(completed=True, finished=time.time())
    finally:
        # Even a mid-cleanup locked file must not leave deleted source marked
        # resumable. Completed previews/publication records are still intact.
        atomic_json(receipt_path, receipt)
        for folder, old in records:
            job = _read(folder/'job.json')
            job['storage_cleanup'] = {'completed': receipt['completed'], 'receipt': str(receipt_path),
                'source_removed': bool(job.get('source') and not Path(job['source']).is_file()),
                'revisions_require_source_download': True}
            atomic_json(folder/'job.json', job)
    return receipt


def cleanup_install_cache(state):
    """Only our explicit pip --cache-dir; never the user's global pip cache."""
    state = Path(state).resolve(); root = state/'install-cache'
    if not root.exists():
        return {'completed': True, 'deleted_bytes': 0, 'scope': 'project installation cache only'}
    _safe(root, state)
    targets = list(_files(root)); count = 0
    for p in targets:
        _safe(p, root)
        count += p.stat().st_size; p.unlink()
    result = {'completed': True, 'deleted_bytes': count, 'scope': 'project installation cache only'}
    atomic_json(state/'install-cache-cleanup.json', result)
    return result
