"""Direct PyInstaller entry point; no child Python or Tk process is needed."""
import argparse
import os
from pathlib import Path
import time
import webbrowser
from reviewproto.web_workbench import Workbench
from reviewproto.local_io import atomic, encoded


def main(argv=None):
    parser=argparse.ArgumentParser(description='评语分析网页工作台')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--data-dir',default=str(Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'ReviewProject'/'workbench'))
    parser.add_argument('--ready-file')
    args=parser.parse_args(argv)
    with Workbench(args.data_dir,args.port) as app:
        if args.ready_file: atomic(Path(args.ready_file),encoded({'url':app.url,'pid':os.getpid()}))
        if not args.no_browser: webbrowser.open(app.url)
        try:
            while not app.closed.wait(.2): pass
        except KeyboardInterrupt: pass
    return 0


if __name__=='__main__': raise SystemExit(main())
