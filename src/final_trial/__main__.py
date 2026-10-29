"""Manual cloud entry point and offline re-export; never starts a paid run by default."""
import argparse
import json
from pathlib import Path
from .runner import Config, FinalRunner, preflight, write


def main():
    parser=argparse.ArgumentParser(description='Zaključni nadzorovani preizkus V01 iz Wordove baze')
    parser.add_argument('--preflight',action='store_true')
    parser.add_argument('--report-only',type=Path)
    parser.add_argument('--output-dir',type=Path,default=Path('final-artifacts'))
    parser.add_argument('--knowledge',type=Path)
    args=parser.parse_args()
    try:
        if args.report_only:
            from .reports import build_final_package
            path=build_final_package(json.loads(args.report_only.read_text(encoding='utf-8')),args.output_dir)
            print(str(path));return
        config=Config.environment()
        if args.preflight:
            _,_,_,estimate=preflight(config,args.knowledge)
            args.output_dir.mkdir(parents=True,exist_ok=True);write(args.output_dir/'preflight.json',estimate)
            print(json.dumps(estimate,ensure_ascii=False,indent=2))
            if not estimate['knowledge_compatible']:raise ValueError('Blokirajoča neskladja Wordove baze.')
            if config.mode=='openai' and not estimate['pricing_valid']:raise ValueError('Cenik potrebuje ponovni pregled; brez API-klicev.')
            return
        state=FinalRunner(args.output_dir,config,kb_path=args.knowledge).run()
        print(json.dumps({'status':state['status'],'revisions':[r['label'] for r in state['revisions']],
                          'stop_reason':state['stop_reason'],'api_usage':state['api_usage'],'package':state['package']},ensure_ascii=False))
    except (ValueError,OSError,TypeError) as exc:
        # Do not echo provider messages, response bodies or credentials to Actions logs.
        parser.exit(1,'Preizkus ni zaključen; glej preflight.json, trial.json in 09_API_poraba.json. Koda: '+getattr(exc,'code','validation_or_configuration_failed')+'\n')


if __name__=='__main__':main()
