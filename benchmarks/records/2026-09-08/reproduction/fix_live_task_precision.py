import json
import os
import time
from pathlib import Path
from sqlalchemy import inspect
from include.database.session import engine

engine.echo=False
backup=Path('/app/state/file-tasks-before-double-20260908.json')
with engine.connect() as c:
    rows=[dict(r) for r in c.exec_driver_sql('SELECT * FROM file_tasks').mappings()]
    before={x['name']:str(x['type']) for x in inspect(c).get_columns('file_tasks') if x['name'] in ('start_time','end_time')}
    assert before=={'start_time':'FLOAT','end_time':'FLOAT'},before
    assert not backup.exists()
    descriptor=os.open(backup,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(descriptor,'w') as f:json.dump(rows,f,default=str)
    c.exec_driver_sql('ALTER TABLE file_tasks MODIFY COLUMN start_time DOUBLE NOT NULL, MODIFY COLUMN end_time DOUBLE NULL')
    c.commit()
    after={x['name']:str(x['type']) for x in inspect(c).get_columns('file_tasks') if x['name'] in ('start_time','end_time')}
    count=c.exec_driver_sql('SELECT COUNT(*) FROM file_tasks').scalar()
    assert count==len(rows)
    assert after=={'start_time':'DOUBLE','end_time':'DOUBLE'},after
    record={'time':time.time(),'before':before,'after':after,'rows_preserved':count,'backup':str(backup),'scope':'file_tasks start_time and end_time only; no version migration'}
    Path('/tmp/production-task-precision-fix.json').write_text(json.dumps(record,indent=2))
    print(json.dumps(record))
