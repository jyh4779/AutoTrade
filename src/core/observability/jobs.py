"""Subprocess evidence: complete output, explicit completion, shared correlation ID."""
import os
import subprocess
from uuid import uuid4
from src.core.observability.events import audit, now_kst


def run_job(name, command, timeout=1800):
    events=audit()
    rid=str(uuid4())
    out=events.root/'log/jobs'/now_kst().date().isoformat()/(name.replace(' ','_')+'_'+rid+'.log')
    out.parent.mkdir(parents=True,exist_ok=True)
    events.emit('JOB_STARTED',required=True,job_name=name,child_run_id=rid,output_path=str(out))
    env=dict(os.environ,ML_RUN_ID=rid,PYTHONIOENCODING='utf-8')
    code=-1
    try:
        with out.open('w',encoding='utf-8') as stream:
            res=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,env=env,
                               timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            code=res.returncode
        return code
    except subprocess.TimeoutExpired:
        events.emit('JOB_TIMEOUT',job_name=name,child_run_id=rid)
        return -1
    finally:
        events.emit('JOB_FINISHED',required=True,job_name=name,child_run_id=rid,returncode=code,output_path=str(out))


def register_expected_jobs():
    events=audit()
    day=now_kst()
    for name,hour,minute in [('Pre-Analysis',9,10),('Morning Routine',10,0),('Afternoon Sell',15,29),('Daily Analysis',15,40)]:
        deadline=day.replace(hour=hour,minute=minute,second=0,microsecond=0)
        events.emit('JOB_EXPECTED',job_name=name,deadline=deadline.isoformat())
        if deadline<day:
            events.emit('JOB_BASELINE_UNKNOWN',job_name=name,reason='deadline_before_scheduler_activation')
