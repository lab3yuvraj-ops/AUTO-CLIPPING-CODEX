"""Start ordinary full-quality downloads immediately; sections for large sources."""
def choose_download(info,max_full_bytes,section_height):
    videos=[f for f in info.get('formats',[]) if f.get('vcodec') not in (None,'none')]
    height=max((f.get('height') or 0 for f in videos),default=0)
    largest=max((f.get('filesize') or f.get('filesize_approx') or (f.get('tbr',0) or 0)*1000/8*info.get('duration',0) for f in videos if (f.get('height') or 0)==height),default=0)
    audio=max((f.get('filesize') or f.get('filesize_approx') or 0 for f in info.get('formats',[]) if f.get('vcodec')=='none' and f.get('acodec') not in (None,'none')),default=0)
    size=largest+audio
    sections=not videos or height>=section_height or size>max_full_bytes
    return {'strategy':'selected-sections' if sections else 'eager-full','height':height,'estimated_bytes':size or None,'max_full_bytes':max_full_bytes,'section_height':section_height,'reason':'resolution/estimated size threshold' if sections else 'ordinary source; full transfer starts immediately after metadata, alongside proxy/draft'}
