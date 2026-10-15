"""yt-dlp CLI with safe Retry-After visibility for caption requests."""
import sys
import json
import yt_dlp


class CaptionDownloader(yt_dlp.YoutubeDL):
    def download_with_info_file(self,info_filename):
        if info_filename!='-':raise ValueError('Caption metadata must be supplied over stdin.')
        info=json.load(sys.stdin)
        # The normal CLI silently re-extracts the URL after an info-file
        # download failure. Caption retries must belong only to our controller.
        self.process_ie_result(self.sanitize_info(info),download=True)
        return self._download_retcode

    def report_error(self,message,*args,**kwargs):
        error=sys.exc_info()[1];seen=set()
        while error is not None and id(error) not in seen:
            seen.add(id(error))
            response=getattr(error,'response',None)
            headers=getattr(error,'headers',None) or getattr(response,'headers',{})
            value=headers.get('Retry-After') if headers else None
            if value is not None:
                value=str(value).replace('\r','').replace('\n','')
                sys.stderr.write('Retry-After: '+value+'\n');sys.stderr.flush();break
            error=getattr(error,'cause',None) or getattr(error,'__cause__',None) or getattr(error,'__context__',None)
        return super().report_error(message,*args,**kwargs)


if __name__=='__main__':
    yt_dlp.YoutubeDL=CaptionDownloader
    yt_dlp.main()
