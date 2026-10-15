"""Private, saved-evidence render replay. Never marks inspection or publishes."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reel_engine.render import file_hash, probe, render_clip
from reel_engine.fast_render import fast_render_clip
from reel_engine.performance import measure


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True)
    p.add_argument('--recipe', required=True, help='Saved edit.json, not draft cues')
    p.add_argument('--output', required=True)
    p.add_argument('--renderer', choices=('legacy', 'direct'), required=True)
    p.add_argument('--threads', type=int, default=2)
    p.add_argument('--no-input-seek', action='store_true', help='Replay the original direct-render decode path')
    args = p.parse_args()
    recipe = json.loads(Path(args.recipe).read_text(encoding='utf-8'))
    out = Path(args.output).resolve()
    if out.exists():
        raise SystemExit('Use a new output directory for each measured replay.')
    out.mkdir(parents=True)
    start = time.perf_counter()
    source_hash = file_hash(args.source)
    hash_seconds = time.perf_counter()-start
    start = time.perf_counter()
    with measure(out,'render') as resources:
        if args.renderer == 'legacy':
            info = render_clip(args.source, recipe['edit'], recipe['tracking'], out/'story.mp4', {})
        else:
            info = fast_render_clip(args.source, recipe['edit'], recipe['tracking'], out/'story.mp4', {'input_seek':not args.no_input_seek}, args.threads)
    elapsed = time.perf_counter()-start
    result = {'renderer': args.renderer, 'seconds': elapsed, 'source_hash_seconds': hash_seconds,
              'source_sha256': source_hash, 'recipe_sha256': file_hash(args.recipe),
              'render_info': info, 'probe': probe(out/'story.mp4'),'resources':resources,
              'reused': ['source footage', 'selected passage', 'verified words', 'reviewed framing plan'],
              'fresh_work': ['camera planning', 'caption events', 'video encoding'],
              'not_end_to_end': True, 'inspection_or_publication_approved': False}
    (out/'measurement.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'seconds': elapsed, 'timings': info['timings'], 'output': str(out)}))


if __name__ == '__main__':
    main()
