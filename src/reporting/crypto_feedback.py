from src.markets.crypto.runtime import storage_path
"""Read persisted crypto research results; never fetch prices or place orders."""
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from src.core.observability.events import ROOT
from src.core.research.validation import temporal_split


def report(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row
        samples=[dict(r) for r in c.execute('SELECT s.strategy,s.at signal_at,o.at label_at,s.score,s.reason,o.return_pct FROM signals s JOIN outcomes o ON s.id=o.id ORDER BY s.at')]
    if not samples:
        return dict(status='UNKNOWN',reason='NO_MATURE_OUTCOMES',weight_changes_applied=False)
    times=sorted({r['signal_at'] for r in samples})
    boundary=times[int(len(times)*.7)]
    train,test,excluded=temporal_split(samples,boundary,900)
    result=dict(status='RESEARCH_ONLY',boundary=boundary,training=len(train),testing=len(test),
                excluded_overlap=len(excluded),weight_changes_applied=False,strategies={})
    for strategy in sorted({r['strategy'] for r in samples}):
        values=[r['return_pct'] for r in test if r['strategy']==strategy]
        result['strategies'][strategy]=dict(test_count=len(values),
            mean_return=sum(values)/len(values) if values else None)
    result['performance_validation']='NOT_ESTABLISHED'
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args()
    data=report(storage_path(args.root)/'data/research.db')
    out=storage_path(args.root)/'reports/feedback.json'
    out.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    print(out)
