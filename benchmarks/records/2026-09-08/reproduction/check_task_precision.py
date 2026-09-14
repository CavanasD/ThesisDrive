import json
import time
from sqlalchemy import inspect
from include.database.session import engine

engine.echo=False
with engine.connect() as c:
    columns={x['name']:str(x['type']) for x in inspect(c).get_columns('file_tasks') if x['name'] in ('start_time','end_time')}
    recent=c.exec_driver_sql('SELECT start_time,end_time,status FROM file_tasks ORDER BY start_time DESC LIMIT 3').all()
    c.exec_driver_sql('CREATE TEMPORARY TABLE thesis_time_precision (f FLOAT,d DOUBLE)')
    samples=[1788877840.662578,1788877840.762578]
    for value in samples:
        c.exec_driver_sql('INSERT INTO thesis_time_precision VALUES (%s,%s)',(value,value))
    stored=c.exec_driver_sql('SELECT f,d FROM thesis_time_precision').all()
    print(json.dumps({'columns':columns,'now':time.time(),'recent':[list(r) for r in recent],'probe':[{'input':x,'float':r[0],'double':r[1],'float_error_seconds':r[0]-x} for x,r in zip(samples,stored)]}))
