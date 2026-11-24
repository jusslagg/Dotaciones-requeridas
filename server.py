"""CAT planning: WSGI application, SQLite, no external services."""
import os, sys, json, sqlite3, secrets, hashlib, hmac, math, time
import calendar
from pathlib import Path
from datetime import datetime, timezone, date, timedelta
from urllib.parse import parse_qs
from http.cookies import SimpleCookie
from contextlib import contextmanager
from wsgiref.simple_server import make_server, WSGIServer
from socketserver import ThreadingMixIn

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('CAT_DATA_DIR', ROOT/'data')).resolve()
NAMES=['Carolina','Ismael','Mariela','Roxana','Salvador']
DEFAULT_DISPLAY={'Carolina':'SURACE, CAROLINA VICTORIA','Salvador':'ALMEIRA, SALVADOR EMILIO','Ismael':'RISSI PEREIRA, ISMAEL NICOLAS','Mariela':'DITTO, MARIELA','Roxana':'LOPEZ DE LA VEGA, ROXANA'}
PREVIOUS_DISPLAY={'Carolina':'Surace, Carolina','Salvador':'Alimera, Salvador','Ismael':'Rissi, Ismael','Mariela':'Ditto, Mariela','Roxana':'de la Vega, Roxana'}
SCHEMA='''CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY, hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plan(id INTEGER PRIMARY KEY,jefe TEXT NOT NULL,service TEXT NOT NULL,day TEXT NOT NULL,kind TEXT NOT NULL,p REAL NOT NULL,h REAL NOT NULL,p0 REAL NOT NULL,h0 REAL NOT NULL,rev INTEGER NOT NULL DEFAULT 0, UNIQUE(jefe,service,day));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,batch TEXT NOT NULL,stamp TEXT NOT NULL,actor TEXT NOT NULL,jefe TEXT NOT NULL,service TEXT NOT NULL,day TEXT NOT NULL,p_old REAL,h_old REAL,p_new REAL,h_new REAL,delta REAL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,actor TEXT,csrf TEXT NOT NULL,expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS absences(id INTEGER PRIMARY KEY, jefe TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL, reason TEXT NOT NULL, cancelled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS coverages(absence_id INTEGER NOT NULL REFERENCES absences(id), service TEXT NOT NULL, substitute TEXT NOT NULL, PRIMARY KEY(absence_id,service));
CREATE TABLE IF NOT EXISTS admin_audit(id INTEGER PRIMARY KEY, stamp TEXT NOT NULL, actor TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS periods(month TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS holidays(day TEXT PRIMARY KEY,name TEXT NOT NULL,source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS campaign_clients(jefe TEXT NOT NULL,service TEXT NOT NULL,client TEXT NOT NULL,PRIMARY KEY(jefe,service));
CREATE TABLE IF NOT EXISTS campaign_details(jefe TEXT NOT NULL,service TEXT NOT NULL,province TEXT NOT NULL,site TEXT NOT NULL,subcampaign TEXT NOT NULL,PRIMARY KEY(jefe,service));
CREATE TABLE IF NOT EXISTS personal_import_versions(id INTEGER PRIMARY KEY,month TEXT NOT NULL,stamp TEXT NOT NULL,actor TEXT NOT NULL,data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS personal_import_month ON personal_import_versions(month,id);
CREATE TABLE IF NOT EXISTS audit_alias(old_jefe TEXT NOT NULL,old_service TEXT NOT NULL,jefe TEXT NOT NULL,service TEXT NOT NULL,PRIMARY KEY(old_jefe,old_service));
CREATE TRIGGER IF NOT EXISTS admin_audit_no_update BEFORE UPDATE ON admin_audit BEGIN SELECT RAISE(ABORT,'Historial inmutable'); END;
CREATE TRIGGER IF NOT EXISTS admin_audit_no_delete BEFORE DELETE ON admin_audit BEGIN SELECT RAISE(ABORT,'Historial inmutable'); END;
CREATE INDEX IF NOT EXISTS absences_dates ON absences(jefe,start,end,cancelled);
CREATE INDEX IF NOT EXISTS audit_jefe ON audit(jefe,id);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'Historial inmutable'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'Historial inmutable'); END;'''
@contextmanager
def connect():
    db=sqlite3.connect(DATA/'planificacion.sqlite',timeout=15,isolation_level=None)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try: yield db
    finally: db.close()
def initialize():
    DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL'); db.executescript(SCHEMA)
        db.execute('BEGIN IMMEDIATE')
        columns={r['name'] for r in db.execute('PRAGMA table_info(users)')}
        if 'role' not in columns: db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'jefe'"); db.execute("UPDATE users SET role='admin' WHERE name='admin'")
        if 'must_change' not in columns: db.execute('ALTER TABLE users ADD COLUMN must_change INTEGER NOT NULL DEFAULT 0')
        if 'display_name' not in columns: db.execute('ALTER TABLE users ADD COLUMN display_name TEXT')
        if not db.execute("SELECT 1 FROM settings WHERE key='initial_chiefs_created'").fetchone():
            for name in NAMES:
                if not db.execute('SELECT 1 FROM users WHERE name=?',(name,)).fetchone():
                    db.execute('INSERT INTO users(name,hash,role,must_change) VALUES(?,?,?,1)',(name,pw_hash(name,temporary=True),'jefe'))
            db.execute("INSERT INTO settings VALUES('initial_chiefs_created','1')")
        if not db.execute("SELECT 1 FROM settings WHERE key='chief_display_names_initialized'").fetchone():
            for username,display in DEFAULT_DISPLAY.items():
                db.execute("UPDATE users SET display_name=? WHERE name=? AND role='jefe' AND (display_name IS NULL OR display_name='')",(display,username))
            db.execute("INSERT INTO settings VALUES('chief_display_names_initialized','1')")
        if not db.execute("SELECT 1 FROM settings WHERE key='chief_full_names_initialized'").fetchone():
            for username,display in DEFAULT_DISPLAY.items():
                db.execute("UPDATE users SET display_name=? WHERE name=? AND role='jefe' AND (display_name IS NULL OR display_name='' OR display_name=? OR display_name=?)",(display,username,username,PREVIOUS_DISPLAY[username]))
            db.execute("INSERT INTO settings VALUES('chief_full_names_initialized','1')")
        if not db.execute('SELECT 1 FROM plan LIMIT 1').fetchone():
            rows=json.loads((ROOT/'seed/diciembre_2026.json').read_text(encoding='utf-8'))
            db.executemany('INSERT INTO plan(jefe,service,day,kind,p,h,p0,h0) VALUES(?,?,?,?,?,?,?,?)',[(*r,r[4],r[5]) for r in rows])
        if not db.execute("SELECT 1 FROM settings WHERE key='periods_initialized'").fetchone():
            months=[r[0] for r in db.execute('SELECT DISTINCT substr(day,1,7) FROM plan ORDER BY 1')]
            db.executemany('INSERT OR IGNORE INTO periods(month,enabled) VALUES(?,?)',[(m,int(m==months[-1])) for m in months])
            db.execute("INSERT INTO settings VALUES('periods_initialized','1')")
        if not db.execute("SELECT 1 FROM settings WHERE key='holiday_calendar_initialized'").fetchone():
            db.execute("INSERT OR IGNORE INTO holidays(day,name,source) SELECT DISTINCT day,'Feriado ya registrado','existing' FROM plan WHERE kind='Fer'")
            db.execute("INSERT INTO settings VALUES('holiday_calendar_initialized','1')")
        db.commit()
        if not db.execute("SELECT 1 FROM users WHERE name='admin'").fetchone():
            keyfile=DATA/'setup.key'
            if not keyfile.exists():
                try:
                    fd=os.open(keyfile,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                    with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(32))
                except FileExistsError: pass
            print('Activación inicial (no compartir): '+keyfile.read_text(),flush=True)
class APIError(Exception):
    def __init__(self,message,status=400):self.message=message; self.status=status

def pw_hash(password,temporary=False,pin=False):
    if not isinstance(password,str) or (pin and (len(password)!=8 or not all('0'<=c<='9' for c in password))) or (not temporary and not pin and not 12<=len(password)<=200):raise APIError('La clave debe tener 8 dígitos' if pin else 'Contraseña de 12 a 200 caracteres')
    salt=secrets.token_hex(16); digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex();return salt+':'+digest

def verify(password,encoded):
    if not isinstance(password,str) or len(password)>200:return False
    salt,digest=encoded.split(':');return hmac.compare_digest(digest,hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex())

def new_session(db,actor=None):
    token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(32)
    db.execute('DELETE FROM sessions WHERE expires<?',(int(time.time()),));db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(token,actor,csrf,int(time.time())+43200));return token,csrf

def cookie(token,env,expired=False):
    secure=env.get('wsgi.url_scheme')=='https' or os.environ.get('CAT_SECURE_COOKIE')=='1'
    return ('Set-Cookie',f'cat_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={0 if expired else 43200}'+('; Secure' if secure else ''))

def today():
    # Argentina currently uses UTC-3; TZ database not required on Windows.
    return (datetime.now(timezone.utc)-timedelta(hours=3)).date().isoformat()

def role(actor,db):
    row=db.execute('SELECT role FROM users WHERE name=?',(actor,)).fetchone() if actor else None
    return row['role'] if row else None

def jefe_names(db):
    return [r['name'] for r in db.execute("SELECT name FROM users WHERE role='jefe' ORDER BY name")]

def display_names(db):
    return {r['name']:r['display_name'] or r['name'] for r in db.execute('SELECT name,display_name FROM users')}

def export_catalog(db):
    path=ROOT/'seed/export_catalog.json'
    entries=json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    catalog={(e['jefe'],e['service']):(e['client'],e['campaign']) for e in entries}
    for alias in db.execute('SELECT old_jefe,old_service,jefe,service FROM audit_alias'):
        original=catalog.get((alias['old_jefe'],alias['old_service']))
        if original:
            catalog[(alias['jefe'],alias['service'])]=(original[0],original[1] if alias['service']==alias['old_service'] else alias['service'])
    for entry in db.execute('SELECT jefe,service,client FROM campaign_clients'):
        key=(entry['jefe'],entry['service'])
        previous=catalog.get(key,(entry['client'],entry['service']))
        catalog[key]=(entry['client'],previous[1])
    return catalog

def valid_name(name):
    return isinstance(name,str) and name==name.strip() and 1<=len(name)<=60 and not any(ord(c)<32 for c in name)

def name_taken(db,name):
    return (any(r['name'].casefold()==name.casefold() for r in db.execute('SELECT name FROM users'))
            or any(r['old_jefe'].casefold()==name.casefold() for r in db.execute('SELECT DISTINCT old_jefe FROM audit_alias')))

def period_list(db,actor):
    query='SELECT month,enabled FROM periods' + ('' if role(actor,db)=='admin' else ' WHERE enabled=1') + ' ORDER BY month DESC'
    return [dict(r) for r in db.execute(query)]

def requested_period(db,actor,query):
    available=period_list(db,actor)
    selected=parse_qs(query).get('month',[''])[0]
    if not selected and available:selected=available[0]['month']
    if selected not in {r['month'] for r in available}:raise APIError('Mes no habilitado',403)
    return selected

def accessible_audit(db,allowed,month):
    rows=db.execute("""SELECT audit.*,COALESCE(a.jefe,audit.jefe) AS current_jefe,
        COALESCE(a.service,audit.service) AS current_service FROM audit
        LEFT JOIN audit_alias a ON a.old_jefe=audit.jefe AND a.old_service=audit.service
        WHERE substr(audit.day,1,7)=? ORDER BY audit.id DESC""",(month,))
    result=[]
    for row in rows:
        r=dict(row);owner=r.pop('current_jefe');service=r.pop('current_service')
        if (owner,service) in allowed:
            r['jefe']=owner;r['service']=service;result.append(r)
    return result

def admin_summary(db,month):
    from holiday_catalog import official_non_working_days
    rows=list(db.execute('SELECT * FROM plan WHERE substr(day,1,7)=? ORDER BY jefe,service,day',(month,)))
    catalog=export_catalog(db)
    holidays=official_non_working_days(int(month[:4])) | {r['day'] for r in rows if r['kind']=='Fer'}
    holidays.update(r['day'] for r in db.execute('SELECT day FROM holidays WHERE substr(day,1,7)=?',(month,)))
    days=sorted({r['day'] for r in rows})
    first=next((day for day in days if date.fromisoformat(day).weekday()<5 and day not in holidays),None)
    groups={}
    for r in rows:
        key=(r['jefe'],r['service'])
        client=catalog.get(key,(r['service'].split()[0] if r['service'].split() else '',r['service']))[0]
        item=groups.setdefault(key,{'jefe':r['jefe'],'client':client, 'campaign':r['service'],'required':None,'hours':0})
        if r['day']==first:item['required']=r['p']
        item['hours']+=r['p']*r['h']
    return {'month':month,'first_business_day':first,'rows':list(groups.values())}

def access(db,actor,day=None):
    day=day or today()
    all_services={(r['jefe'],r['service']) for r in db.execute('SELECT DISTINCT jefe,service FROM plan')}
    if role(actor,db)=='admin':return all_services
    if role(actor,db)!='jefe':return set()
    active=list(db.execute('SELECT * FROM absences WHERE cancelled=0 AND start<=? AND end>=?',(day,day)))
    absent={r['jefe'] for r in active}
    if actor in absent:return set()
    allowed={(owner,service) for owner,service in all_services if owner==actor}
    for a in active:
        allowed.update((a['jefe'],r['service']) for r in db.execute('SELECT service FROM coverages WHERE absence_id=? AND substitute=?',(a['id'],actor)))
    return allowed & all_services

def admin_log(db,actor,event,detail):
    db.execute('INSERT INTO admin_audit(stamp,actor,event,detail) VALUES(?,?,?,?)',(datetime.now(timezone.utc).isoformat(),actor,event,json.dumps(detail,ensure_ascii=False)))

def rename_campaign_record(db,actor,owner,old,new):
    """Rename within an existing transaction, retaining historical aliases."""
    if not valid_name(new):raise APIError('Nombre de campaña inválido')
    if not db.execute('SELECT 1 FROM plan WHERE jefe=? AND service=?',(owner,old)).fetchone():raise APIError('Campaña inexistente',404)
    if old==new:return
    if any(r['service']!=old and r['service'].casefold()==new.casefold() for r in db.execute('SELECT DISTINCT service FROM plan WHERE jefe=?',(owner,))):raise APIError('Este jefe ya tiene una campaña con ese nombre',409)
    if any(r['old_service'].casefold()==new.casefold() and r['service']!=old for r in db.execute('SELECT old_service,service FROM audit_alias WHERE jefe=?',(owner,))):raise APIError('Ese nombre pertenece al historial de otra campaña',409)
    db.execute('INSERT OR IGNORE INTO audit_alias(old_jefe,old_service,jefe,service) VALUES(?,?,?,?)',(owner,old,owner,old))
    db.execute('UPDATE audit_alias SET service=? WHERE jefe=? AND service=?',(new,owner,old))
    db.execute('UPDATE plan SET service=?,rev=rev+1 WHERE jefe=? AND service=?',(new,owner,old))
    db.execute('UPDATE campaign_clients SET service=? WHERE jefe=? AND service=?',(new,owner,old))
    db.execute('UPDATE campaign_details SET service=? WHERE jefe=? AND service=?',(new,owner,old))
    db.execute('UPDATE coverages SET service=? WHERE service=? AND absence_id IN (SELECT id FROM absences WHERE jefe=?)',(new,old,owner))
    admin_log(db,actor,'RENOMBRAR_CAMPAÑA',{'jefe':owner,'before':old,'after':new})

def publish_personal(db,actor,version_id,assignments):
    if type(version_id) is not int or not isinstance(assignments,list):raise APIError('Datos de incorporación inválidos')
    db.execute('BEGIN IMMEDIATE')
    try:
        version=db.execute('SELECT * FROM personal_import_versions WHERE id=?',(version_id,)).fetchone()
        if not version:raise APIError('Previa no encontrada',404)
        if db.execute('SELECT MAX(id) FROM personal_import_versions WHERE month=?',(version['month'],)).fetchone()[0]!=version_id:raise APIError('Hay una previa más reciente. Volvé a cargarla.',409)
        if not db.execute('SELECT 1 FROM periods WHERE month=?',(version['month'],)).fetchone():raise APIError('El mes todavía no existe en la planificación. Crealo antes de incorporar la previa.',409)
        data=json.loads(version['data']);rows=data['rows']
        if len(assignments)!=len(rows):raise APIError('Revisá la asignación de todas las campañas')
        if data.get('block_differences'):raise APIError('Los bloques de horas y dotación no coinciden. Corregí el archivo antes de incorporarlo.',409)
        suggested_owners={name for item in rows for name in item.get('suggested_responsibles',[])}
        catalog=export_catalog(db)
        old_clients={(r['jefe'],r['service']):catalog.get((r['jefe'],r['service']),(r['service'].split()[0],r['service']))[0] for r in db.execute('SELECT DISTINCT jefe,service FROM plan')}
        existing_days={r['day']:r['kind'] for r in db.execute('SELECT day,MIN(kind) AS kind FROM plan WHERE substr(day,1,7)=? GROUP BY day',(version['month'],))}
        holidays={r['day'] for r in db.execute('SELECT day FROM holidays WHERE substr(day,1,7)=?',(version['month'],))}
        weekdays=['Lun','Mar','Mié','Jue','Vie','Sáb','Dom']
        stamp=datetime.now(timezone.utc).isoformat();batch=secrets.token_hex(12)
        seen=set();seen_services=set();created_users=[];inserted=0;updated=0;pending_campaigns=[]
        for item,assignment in zip(rows,assignments):
            if item.get('missing_data'):
                pending_campaigns.append(item['campaign'])
                continue
            if not isinstance(assignment,dict):raise APIError('Asignación inválida')
            owner=assignment.get('name');create=assignment.get('create')
            if not valid_name(owner) or type(create) is not bool:raise APIError('Seleccioná un responsable para cada campaña')
            if create:
                if owner not in suggested_owners:raise APIError('El responsable nuevo debe coincidir con el listado de referencia')
                existing=role(owner,db)
                if not existing:
                    if name_taken(db,owner):raise APIError('Ya existe un usuario con ese nombre',409)
                    db.execute("INSERT INTO users(name,hash,role,must_change,display_name) VALUES(?,?,'jefe',1,?)",(owner,pw_hash(owner,temporary=True),owner))
                    admin_log(db,actor,'CREAR_JEFE',{'name':owner,'origin':'PERSONAL'})
                    created_users.append(owner)
                elif existing!='jefe':raise APIError('El responsable debe tener rol de jefe')
            elif role(owner,db)!='jefe':raise APIError('El responsable seleccionado no existe o no es jefe')
            name=item.get('reference_campaign') or item['campaign']
            if not valid_name(name):raise APIError('El nombre de una campaña no es válido')
            key=(owner,name)
            if key in seen or name.casefold() in seen_services:raise APIError('Hay campañas repetidas en la importación',409)
            seen.add(key);seen_services.add(name.casefold())
            if any(other==owner and service!=name and service.casefold()==name.casefold() for other,service in old_clients):raise APIError('La campaña '+name+' ya existe con otra forma de escritura',409)
            if key in old_clients and old_clients[key].casefold()!='personal':raise APIError('La campaña '+name+' ya pertenece a otro cliente',409)
            if any(other!=owner and service.casefold()==name.casefold() and client.casefold()=='personal' for (other,service),client in old_clients.items()):raise APIError('La campaña '+name+' ya está asignada a otro responsable',409)
            db.execute("INSERT INTO campaign_clients(jefe,service,client) VALUES(?,?,'PERSONAL') ON CONFLICT(jefe,service) DO UPDATE SET client='PERSONAL'",key)
            if 'source_site' in item:
                db.execute('''INSERT INTO campaign_details(jefe,service,province,site,subcampaign) VALUES(?,?,?,?,?)
                    ON CONFLICT(jefe,service) DO UPDATE SET province=excluded.province,site=excluded.site,subcampaign=excluded.subcampaign''',
                    (owner,name,item['source_province'],item['source_site'],item['source_subcampaign']))
            for day in item['days']:
                hours=day['hours'];people=hours/6;daystr=day['day']
                if not daystr.startswith(version['month']+'-') or not math.isfinite(people):raise APIError('Fecha o valor inválido en la previa')
                current=db.execute('SELECT * FROM plan WHERE jefe=? AND service=? AND day=?',(owner,name,daystr)).fetchone()
                if current:
                    if current['p']==people and current['h']==6:continue
                    db.execute('UPDATE plan SET p=?,h=6,rev=rev+1 WHERE id=?',(people,current['id']))
                    db.execute('INSERT INTO audit(batch,stamp,actor,jefe,service,day,p_old,h_old,p_new,h_new,delta) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(batch,stamp,actor,owner,name,daystr,current['p'],current['h'],people,6,hours-current['p']*current['h']))
                    updated+=1
                else:
                    actual=date.fromisoformat(daystr)
                    kind='Fer' if daystr in holidays else existing_days.get(daystr,weekdays[actual.weekday()])
                    db.execute('INSERT INTO plan(jefe,service,day,kind,p,h,p0,h0) VALUES(?,?,?,?,?,6,?,6)',(owner,name,daystr,kind,people,people))
                    inserted+=1
        count=len(rows)-len(pending_campaigns)
        if not count:raise APIError('No hay campañas con datos completos para incorporar')
        admin_log(db,actor,'INCORPORAR_PERSONAL',{'version_id':version_id,'month':version['month'],'campaigns':count,'pending_campaigns':pending_campaigns,'inserted':inserted,'updated':updated,'created_users':created_users,'batch':batch})
        db.commit()
        return {'ok':True,'month':version['month'],'campaigns':count,'pending_campaigns':pending_campaigns,'inserted':inserted,'updated':updated,'created_users':created_users}
    except BaseException:db.rollback();raise

def management(db):
    absences=[]
    for a in db.execute('SELECT * FROM absences ORDER BY start DESC,id DESC'):
        item=dict(a);item['assignments']={r['service']:r['substitute'] for r in db.execute('SELECT service,substitute FROM coverages WHERE absence_id=?',(a['id'],))};absences.append(item)
    accounts=[{'name':r['name'],'display_name':r['display_name'] or r['name'],'role':r['role'],'active':True} for r in db.execute('SELECT name,role,display_name FROM users ORDER BY role,name')]
    catalog=export_catalog(db)
    campaigns=[dict(r) for r in db.execute('SELECT DISTINCT jefe,service FROM plan ORDER BY jefe,service')]
    for c in campaigns:c['client']=catalog.get((c['jefe'],c['service']),(c['service'].split()[0] if c['service'].split() else '',c['service']))[0]
    return {'today':today(),'absences':absences,'accounts':accounts,'campaigns':campaigns,'events':[dict(r) for r in db.execute('SELECT * FROM admin_audit ORDER BY id DESC')]}

def manage_absence(db,actor,payload,cancel=False):
    db.execute('BEGIN IMMEDIATE')
    try:
        aid=payload.get('id'); old=None
        if aid is not None:
            if type(aid) is not int:raise APIError('ID inválido')
            old=db.execute('SELECT * FROM absences WHERE id=? AND cancelled=0',(aid,)).fetchone()
            if not old:raise APIError('Ausencia no encontrada',404)
        if cancel:
            if not old:raise APIError('Indicá una ausencia')
            if old['end']<today():raise APIError('No se puede cancelar una ausencia finalizada')
            db.execute('UPDATE absences SET cancelled=1 WHERE id=?',(aid,));admin_log(db,actor,'CANCELAR_AUSENCIA',dict(old));db.commit();return {'ok':True}
        owner=payload.get('jefe'); start=payload.get('start'); end=payload.get('end'); reason=payload.get('reason','Vacaciones'); assignments=payload.get('assignments',{})
        if role(owner,db)!='jefe' or reason not in ('Vacaciones','Licencia','Otra ausencia') or not isinstance(assignments,dict):raise APIError('Datos de ausencia inválidos')
        try:
            if date.fromisoformat(start).isoformat()!=start or date.fromisoformat(end).isoformat()!=end or start>end or end<today():raise ValueError()
        except (TypeError,ValueError):raise APIError('Rango de ausencia inválido o finalizado')
        if old:
            if old['end']<today():raise APIError('No se puede editar una ausencia finalizada')
            if old['start']<=today() and (owner!=old['jefe'] or start!=old['start']):raise APIError('Una ausencia iniciada mantiene su titular y fecha de inicio')
        elif start<today():raise APIError('La fecha de inicio no puede ser anterior a hoy')
        services={r[0] for r in db.execute('SELECT DISTINCT service FROM plan WHERE jefe=?',(owner,))}
        if not services or not set(assignments)<=services:raise APIError('Campañas inválidas')
        if db.execute('SELECT 1 FROM absences WHERE cancelled=0 AND jefe=? AND start<=? AND end>=? AND id<>?',(owner,end,start,aid or -1)).fetchone():raise APIError('El jefe ya tiene una ausencia superpuesta',409)
        # A new absence cannot make an already assigned substitute unavailable.
        if db.execute('SELECT 1 FROM coverages c JOIN absences a ON a.id=c.absence_id WHERE a.cancelled=0 AND c.substitute=? AND a.start<=? AND a.end>=? AND a.id<>?',(owner,end,start,aid or -1)).fetchone():raise APIError('Este jefe tiene una cobertura superpuesta; reasignala primero',409)
        clean={}
        for service,sub in assignments.items():
            if sub=='':continue
            if role(sub,db)!='jefe' or sub==owner:raise APIError('Suplente inválido o sin cuenta habilitada')
            if db.execute('SELECT 1 FROM absences WHERE cancelled=0 AND jefe=? AND start<=? AND end>=? AND id<>?',(sub,end,start,aid or -1)).fetchone():raise APIError(f'{sub} tiene una ausencia superpuesta',409)
            clean[service]=sub
        previous=None
        if old:
            previous={'absence':dict(old),'assignments':{r['service']:r['substitute'] for r in db.execute('SELECT * FROM coverages WHERE absence_id=?',(aid,))}}
            db.execute('UPDATE absences SET jefe=?,start=?,end=?,reason=? WHERE id=?',(owner,start,end,reason,aid));db.execute('DELETE FROM coverages WHERE absence_id=?',(aid,))
        else:
            aid=db.execute('INSERT INTO absences(jefe,start,end,reason) VALUES(?,?,?,?)',(owner,start,end,reason)).lastrowid
        db.executemany('INSERT INTO coverages VALUES(?,?,?)',[(aid,k,v) for k,v in clean.items()]);admin_log(db,actor,'EDITAR_AUSENCIA' if old else 'CREAR_AUSENCIA',{'id':aid,'previous':previous,'jefe':owner,'start':start,'end':end,'reason':reason,'assignments':clean});db.commit();return {'ok':True,'id':aid}
    except BaseException:db.rollback();raise

def save(db,actor,changes):
    if not isinstance(changes,list) or len(changes)>2000:raise APIError('Cambios inválidos')
    batch=secrets.token_hex(12); stamp=datetime.now(timezone.utc).isoformat(); count=0; seen=set()
    db.execute('BEGIN IMMEDIATE')
    try:
        allowed=access(db,actor)
        for c in changes:
            if not isinstance(c,dict) or type(c.get('id')) is not int or type(c.get('rev')) is not int:raise APIError('Registro inválido')
            if c['id'] in seen:raise APIError('Registro duplicado')
            seen.add(c['id']);r=db.execute('SELECT * FROM plan WHERE id=?',(c['id'],)).fetchone()
            if not r or (r['jefe'],r['service']) not in allowed:raise APIError('Sin permiso sobre la campaña',403)
            if role(actor,db)!='admin' and not db.execute('SELECT 1 FROM periods WHERE month=? AND enabled=1',(r['day'][:7],)).fetchone():raise APIError('El mes ya no está habilitado',403)
            if c['rev']!=r['rev']:raise APIError('Otro usuario modificó estos datos. Actualizá antes de guardar.',409)
            p,h=c.get('p'),c.get('h')
            if type(p) not in (int,float) or type(h) not in (int,float) or not (0<=p<=100000 and 0<=h<=24):raise APIError('Dotación o jornada fuera de rango')
            if p==r['p'] and h==r['h']:continue
            db.execute('UPDATE plan SET p=?,h=?,rev=rev+1 WHERE id=?',(p,h,r['id']))
            db.execute('INSERT INTO audit(batch,stamp,actor,jefe,service,day,p_old,h_old,p_new,h_new,delta) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(batch,stamp,actor,r['jefe'],r['service'],r['day'],r['p'],r['h'],p,h,p*h-r['p']*r['h']));count+=1
        db.commit();return {'ok':True,'count':count}
    except BaseException:db.rollback();raise

def application(env,start_response):
    headers=[('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('X-Frame-Options','DENY'),('Referrer-Policy','no-referrer'),('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")]
    def response(body,status=200,ctype='application/json; charset=utf-8'):
        from http import HTTPStatus
        if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False,allow_nan=False).encode()
        start_response(f'{status} {HTTPStatus(status).phrase}',headers+[('Content-Type',ctype),('Content-Length',str(len(body)))]);return [body]
    try:
        action=parse_qs(env.get('QUERY_STRING','')).get('api',[''])[0]; method=env['REQUEST_METHOD']
        if not action:
            file={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/styles.css':'styles.css'}.get(env['PATH_INFO'])
            if method!='GET' or not file:raise APIError('No encontrado',404)
            return response((ROOT/'web'/file).read_bytes(),ctype={'html':'text/html','js':'text/javascript','css':'text/css'}[file.split('.')[-1]]+'; charset=utf-8')
        with connect() as db:
            cookies=SimpleCookie();cookies.load(env.get('HTTP_COOKIE',''));token=cookies['cat_session'].value if 'cat_session' in cookies else ''
            session=db.execute('SELECT * FROM sessions WHERE token=? AND expires>?',(token,int(time.time()))).fetchone()
            if not session:
                token,csrf=new_session(db);headers.append(cookie(token,env));actor=None
            else:actor=session['actor'];csrf=session['csrf']
            setup=not bool(db.execute("SELECT 1 FROM users WHERE name='admin'").fetchone())
            must_change=bool(db.execute('SELECT must_change FROM users WHERE name=?',(actor,)).fetchone()['must_change']) if role(actor,db) else False
            if action=='status' and method=='GET':return response({'actor':actor,'csrf':csrf,'setup':setup,'names':jefe_names(db),'display_names':display_names(db) if actor else {},'role':role(actor,db),'must_change':must_change,'periods':period_list(db,actor) if actor else []})
            if must_change and action not in ('change_password','logout'):raise APIError('Debés cambiar tu clave antes de continuar',403)
            if action=='data' and method=='GET':
                if not actor:raise APIError('Iniciar sesión',401)
                db.execute('BEGIN');month=requested_period(db,actor,env.get('QUERY_STRING',''));allowed=access(db,actor);catalog=export_catalog(db);plan=[dict(r) for r in db.execute('SELECT * FROM plan WHERE substr(day,1,7)=? ORDER BY jefe,service,day',(month,)) if (r['jefe'],r['service']) in allowed]
                for r in plan:r['client']=catalog.get((r['jefe'],r['service']),(r['service'].split()[0] if r['service'].split() else '',r['service']))[0]
                audit=accessible_audit(db,allowed,month);db.commit();return response({'plan':plan,'audit':audit,'today':today(),'month':month,'periods':period_list(db,actor)})
            if action=='export_excel' and method=='GET':
                if not actor:raise APIError('Iniciar sesión',401)
                db.execute('BEGIN')
                month=requested_period(db,actor,env.get('QUERY_STRING',''))
                allowed=access(db,actor)
                rows=[dict(r) for r in db.execute('SELECT * FROM plan WHERE substr(day,1,7)=? ORDER BY jefe,service,day',(month,)) if (r['jefe'],r['service']) in allowed]
                db.commit()
                if not rows:raise APIError('No hay planificación disponible para exportar',404)
                from excel_export import planning_workbook
                headers.append(('Content-Disposition','attachment; filename="planificacion.xlsx"'))
                return response(planning_workbook(rows,display_names(db),export_catalog(db)),ctype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            if action=='management' and method=='GET':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                db.execute('BEGIN'); result=management(db); db.commit();return response(result)
            if action=='admin_summary' and method=='GET':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                db.execute('BEGIN');month=requested_period(db,actor,env.get('QUERY_STRING',''));result=admin_summary(db,month);db.commit();return response(result)
            if action in ('site_report','export_site_report') and method=='GET':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                from site_report import report,workbook,available,filter_report
                filters=parse_qs(env.get('QUERY_STRING',''))
                month=filters.get('month',[''])[0]
                if month not in available(db):raise APIError('Mes sin datos disponibles',404)
                db.execute('BEGIN');result=report(db,month,admin_summary,display_names(db));db.commit()
                if not result:raise APIError('Mes sin datos disponibles',404)
                if action=='site_report':return response(result)
                headers.append(('Content-Disposition','attachment; filename="resumen_site_front.xlsx"'))
                result=filter_report(result,filters.get('owner',[]),filters.get('campaign',[]),filters.get('front_campaign',[]))
                return response(workbook(result),ctype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            if action=='holidays' and method=='GET':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                try:
                    year=int(parse_qs(env.get('QUERY_STRING','')).get('year',[today()[:4]])[0])
                    if not 1900<=year<=9999:raise ValueError()
                except (ValueError,TypeError):raise APIError('Año inválido')
                from holiday_catalog import official_holidays
                marked=[dict(r) for r in db.execute('SELECT day,name,source FROM holidays WHERE substr(day,1,4)=? ORDER BY day',(str(year),))]
                return response({'year':year,'official':official_holidays(year),'marked':marked})
            if action=='personal_draft' and method=='GET':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                month=parse_qs(env.get('QUERY_STRING','')).get('month',[''])[0]
                row=db.execute('SELECT id,month,stamp,actor,data FROM personal_import_versions WHERE month=? ORDER BY id DESC LIMIT 1',(month,)).fetchone()
                if not row:return response({'draft':None})
                return response({'draft':{'id':row['id'],'month':row['month'],'stamp':row['stamp'],'actor':row['actor'],'data':json.loads(row['data'])}})
            if action=='export_summary' and method=='GET':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                query=env.get('QUERY_STRING','');filters=parse_qs(query,keep_blank_values=True)
                db.execute('BEGIN');month=requested_period(db,actor,query);result=admin_summary(db,month);names=display_names(db);db.commit()
                for field,param in [('jefe','chief'),('client','client'),('campaign','campaign')]:
                    values={value for value in filters.get(param,[]) if value}
                    if values:result['rows']=[row for row in result['rows'] if row[field] in values]
                from excel_export import summary_workbook
                headers.append(('Content-Disposition','attachment; filename="resumen_campanas.xlsx"'))
                return response(summary_workbook(result,names),ctype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            if method!='POST':raise APIError('Método no permitido',405)
            length=int(env.get('CONTENT_LENGTH') or 0)
            if length<1 or length>2_000_000:raise APIError('Solicitud inválida',413)
            try: payload=json.loads(env['wsgi.input'].read(length))
            except ValueError:raise APIError('JSON inválido')
            if not isinstance(payload,dict) or not isinstance(payload.get('csrf'),str) or not hmac.compare_digest(csrf,payload['csrf']):raise APIError('Sesión inválida',403)
            if action=='setup':
                keyfile=DATA/'setup.key';provided=payload.get('key','')
                if not setup or not keyfile.exists() or not isinstance(provided,str) or not hmac.compare_digest(keyfile.read_text(),provided):raise APIError('Clave incorrecta',403)
                db.execute("INSERT INTO users(name,hash,role,must_change) VALUES(?,?,'admin',0)",('admin',pw_hash(payload.get('password'))));keyfile.unlink(missing_ok=True);return response({'ok':True})
            if action=='login':
                name=payload.get('name')
                if isinstance(name,str) and name.lower()=='admin':name='admin'
                row=db.execute('SELECT hash FROM users WHERE name=?',(name,)).fetchone() if isinstance(name,str) else None
                if not row or not verify(payload.get('password'),row['hash']):time.sleep(.35);raise APIError('Credenciales incorrectas',403)
                db.execute('DELETE FROM sessions WHERE token=?',(token,));token,_=new_session(db,name);headers.append(cookie(token,env));return response({'ok':True})
            if not actor:raise APIError('Iniciar sesión',401)
            if action=='logout':db.execute('DELETE FROM sessions WHERE token=?',(token,));headers.append(cookie('',env,True));return response({'ok':True})
            if action=='change_password':
                if not must_change:raise APIError('No hay cambio de clave pendiente',400)
                hashed=pw_hash(payload.get('password'),pin=True)
                db.execute('BEGIN IMMEDIATE'); db.execute('UPDATE users SET hash=?,must_change=0 WHERE name=?',(hashed,actor)); db.execute('DELETE FROM sessions WHERE actor=? AND token<>?',(actor,token)); db.commit(); return response({'ok':True})
            if action in ('personal_preview','personal_save'):
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                from personal_import import PersonalImportError,parse_payload,with_responsibles
                try:
                    result=with_responsibles(parse_payload(payload),ROOT/'seed/personal_responsables.json')
                except PersonalImportError as error:raise APIError(str(error))
                if action=='personal_preview':return response(result)
                db.execute('BEGIN IMMEDIATE')
                try:
                    stamp=datetime.now(timezone.utc).isoformat()
                    cursor=db.execute('INSERT INTO personal_import_versions(month,stamp,actor,data) VALUES(?,?,?,?)',(result['month'],stamp,actor,json.dumps(result,ensure_ascii=False)))
                    admin_log(db,actor,'GUARDAR_PREVIA_PERSONAL',{'id':cursor.lastrowid,'month':result['month'],'campaigns':result['campaigns'],'total_differences':len(result['total_differences'])})
                    db.commit()
                except BaseException:db.rollback();raise
                return response({'ok':True,'id':cursor.lastrowid,'month':result['month']})
            if action=='personal_publish':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                return response(publish_personal(db,actor,payload.get('id'),payload.get('assignments')))
            if action in ('holiday_mark','holiday_remove'):
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                day=payload.get('day')
                try:
                    parsed=date.fromisoformat(day)
                    if parsed.isoformat()!=day:raise ValueError()
                except (ValueError,TypeError):raise APIError('Fecha inválida')
                db.execute('BEGIN IMMEDIATE')
                try:
                    old=db.execute('SELECT * FROM holidays WHERE day=?',(day,)).fetchone()
                    if action=='holiday_mark':
                        source=payload.get('source');name=payload.get('name')
                        if source=='official':
                            from holiday_catalog import official_holidays
                            official=next((r for r in official_holidays(parsed.year) if r['day']==day),None)
                            if not official:raise APIError('Feriado oficial no disponible para esa fecha')
                            name=official['name']
                        elif source=='custom':
                            if not isinstance(name,str) or name!=name.strip() or not 1<=len(name)<=150 or any(ord(c)<32 for c in name):raise APIError('Indicá un nombre válido')
                        else:raise APIError('Tipo de feriado inválido')
                        if old and old['source']!='existing':raise APIError('Ya hay un feriado marcado en esa fecha',409)
                        db.execute('INSERT INTO holidays(day,name,source) VALUES(?,?,?) ON CONFLICT(day) DO UPDATE SET name=excluded.name,source=excluded.source',(day,name,source))
                        updated=db.execute("UPDATE plan SET kind='Fer',rev=rev+1 WHERE day=? AND kind<>'Fer'",(day,)).rowcount
                        admin_log(db,actor,'MARCAR_FERIADO',{'day':day,'name':name,'source':source,'records':updated})
                    else:
                        if not old:raise APIError('Feriado no encontrado',404)
                        db.execute('DELETE FROM holidays WHERE day=?',(day,))
                        weekday=['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'][parsed.weekday()]
                        updated=db.execute("UPDATE plan SET kind=?,rev=rev+1 WHERE day=? AND kind='Fer'",(weekday,day)).rowcount
                        admin_log(db,actor,'QUITAR_FERIADO',{'day':day,'name':old['name'],'source':old['source'],'records':updated})
                    db.commit()
                except BaseException:db.rollback();raise
                return response({'ok':True,'records':updated})
            if action=='create_admin':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                name=payload.get('name'); password=payload.get('password')
                if not valid_name(name):raise APIError('Nombre de usuario inválido')
                if name_taken(db,name):raise APIError('El usuario ya existe',409)
                hashed=pw_hash(password); db.execute('BEGIN IMMEDIATE')
                try:
                    db.execute("INSERT INTO users(name,hash,role,must_change) VALUES(?,?,'admin',0)",(name,hashed)); admin_log(db,actor,'CREAR_ADMIN',{'name':name}); db.commit()
                except BaseException: db.rollback(); raise
                return response({'ok':True})
            if action=='create_jefe':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                name=payload.get('name')
                if not valid_name(name):raise APIError('Nombre de usuario inválido')
                hashed=pw_hash(name,temporary=True);db.execute('BEGIN IMMEDIATE')
                try:
                    if name_taken(db,name):raise APIError('El usuario ya existe',409)
                    db.execute("INSERT INTO users(name,hash,role,must_change) VALUES(?,?,'jefe',1)",(name,hashed))
                    admin_log(db,actor,'CREAR_JEFE',{'name':name});db.commit()
                except BaseException:db.rollback();raise
                return response({'ok':True})
            if action=='open_month':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                month=payload.get('month');mode=payload.get('mode')
                try:
                    if not isinstance(month,str) or len(month)!=7 or date.fromisoformat(month+'-01').strftime('%Y-%m')!=month:raise ValueError()
                    first=date.fromisoformat(month+'-01');previous=(first-timedelta(days=1)).strftime('%Y-%m')
                except ValueError:raise APIError('Mes inválido')
                if mode!='weekday':raise APIError('La copia debe ser por día de la semana')
                db.execute('BEGIN IMMEDIATE')
                try:
                    if db.execute('SELECT 1 FROM periods WHERE month=?',(month,)).fetchone():raise APIError('Este mes ya existe; podés habilitarlo sin copiarlo otra vez',409)
                    if not db.execute('SELECT 1 FROM periods WHERE month=?',(previous,)).fetchone():raise APIError('Primero debés crear el mes anterior',409)
                    source=list(db.execute('SELECT * FROM plan WHERE substr(day,1,7)=? ORDER BY day',(previous,)))
                    if not source:raise APIError('El mes anterior no tiene planificación',409)
                    groups={}
                    for r in source:groups.setdefault((r['jefe'],r['service']),[]).append(r)
                    names=['Lun','Mar','Mié','Jue','Vie','Sáb','Dom'];rows=[]
                    holiday_days={r['day'] for r in db.execute('SELECT day FROM holidays WHERE substr(day,1,7)=?',(month,))}
                    for owner,service in groups:
                        entries=groups[(owner,service)]
                        for daynum in range(1,calendar.monthrange(first.year,first.month)[1]+1):
                            target=first.replace(day=daynum)
                            matches=[r for r in entries if date.fromisoformat(r['day']).weekday()==target.weekday()]
                            if not matches:raise APIError('Una campaña no tiene datos suficientes en el mes anterior',409)
                            old=matches[-1]
                            target_day=target.isoformat()
                            rows.append((owner,service,target_day,'Fer' if target_day in holiday_days else names[target.weekday()],old['p'],old['h'],old['p'],old['h']))
                    db.executemany('INSERT INTO plan(jefe,service,day,kind,p,h,p0,h0) VALUES(?,?,?,?,?,?,?,?)',rows)
                    db.execute('UPDATE periods SET enabled=0');db.execute('INSERT INTO periods(month,enabled) VALUES(?,1)',(month,))
                    admin_log(db,actor,'ABRIR_MES',{'month':month,'previous':previous,'mode':mode,'records':len(rows)});db.commit()
                except BaseException:db.rollback();raise
                return response({'ok':True,'records':len(rows)})
            if action=='enable_month':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                month=payload.get('month');db.execute('BEGIN IMMEDIATE')
                try:
                    if not db.execute('SELECT 1 FROM periods WHERE month=?',(month,)).fetchone():raise APIError('Mes inexistente',404)
                    db.execute('UPDATE periods SET enabled=(month=?)',(month,));admin_log(db,actor,'HABILITAR_MES',{'month':month});db.commit()
                except BaseException:db.rollback();raise
                return response({'ok':True})
            if action=='rename_user':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                old=payload.get('name');new=payload.get('new_name')
                if old=='admin':raise APIError('El usuario administrador principal no se puede renombrar')
                if not valid_name(new):raise APIError('Nombre de usuario inválido')
                db.execute('BEGIN IMMEDIATE')
                try:
                    if not role(old,db):raise APIError('Usuario inexistente',404)
                    if name_taken(db,new):raise APIError('El usuario ya existe',409)
                    db.execute('INSERT OR IGNORE INTO audit_alias SELECT DISTINCT jefe,service,jefe,service FROM plan WHERE jefe=?',(old,))
                    db.execute('UPDATE audit_alias SET jefe=? WHERE jefe=?',(new,old))
                    db.execute('UPDATE plan SET jefe=? WHERE jefe=?',(new,old))
                    db.execute('UPDATE campaign_clients SET jefe=? WHERE jefe=?',(new,old))
                    db.execute('UPDATE campaign_details SET jefe=? WHERE jefe=?',(new,old))
                    db.execute('UPDATE absences SET jefe=? WHERE jefe=?',(new,old))
                    db.execute('UPDATE coverages SET substitute=? WHERE substitute=?',(new,old))
                    db.execute('UPDATE users SET name=?,display_name=? WHERE name=?',(new,new,old))
                    db.execute('DELETE FROM sessions WHERE actor=?',(old,))
                    admin_log(db,actor,'RENOMBRAR_USUARIO',{'before':old,'after':new});db.commit()
                except BaseException:db.rollback();raise
                return response({'ok':True})
            if action=='rename_campaign':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                owner=payload.get('jefe');old=payload.get('name');new=payload.get('new_name')
                db.execute('BEGIN IMMEDIATE')
                try:
                    rename_campaign_record(db,actor,owner,old,new);db.commit()
                except BaseException:db.rollback();raise
                return response({'ok':True})
            if action=='set_campaign_client':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                owner=payload.get('jefe');service=payload.get('service');client=payload.get('client')
                if not isinstance(client,str) or client!=client.strip() or not 1<=len(client)<=100 or any(ord(c)<32 for c in client):raise APIError('Cliente inválido')
                db.execute('BEGIN IMMEDIATE')
                try:
                    if not db.execute('SELECT 1 FROM plan WHERE jefe=? AND service=?',(owner,service)).fetchone():raise APIError('Campaña inexistente',404)
                    old=export_catalog(db).get((owner,service),(service.split()[0],service))[0]
                    db.execute('INSERT INTO campaign_clients(jefe,service,client) VALUES(?,?,?) ON CONFLICT(jefe,service) DO UPDATE SET client=excluded.client',(owner,service,client))
                    admin_log(db,actor,'CAMBIAR_CLIENTE',{'jefe':owner,'service':service,'previous':old,'client':client});db.commit()
                except BaseException:db.rollback();raise
                return response({'ok':True})
            if action=='create_campaign':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                name=payload.get('name');owner=payload.get('jefe');client=payload.get('client')
                if not valid_name(name):raise APIError('Nombre de campaña inválido')
                if client is not None and (not isinstance(client,str) or client!=client.strip() or not 1<=len(client)<=100 or any(ord(c)<32 for c in client)):raise APIError('Cliente inválido')
                db.execute('BEGIN IMMEDIATE')
                try:
                    if role(owner,db)!='jefe':raise APIError('Seleccioná un jefe válido')
                    if any(r['service'].casefold()==name.casefold() for r in db.execute('SELECT DISTINCT service FROM plan WHERE jefe=?',(owner,))):raise APIError('Este jefe ya tiene una campaña con ese nombre',409)
                    if any(r['old_service'].casefold()==name.casefold() for r in db.execute('SELECT old_service FROM audit_alias WHERE jefe=?',(owner,))):raise APIError('Ese nombre pertenece al historial de otra campaña',409)
                    days=list(db.execute('SELECT day,MIN(kind) AS kind FROM plan WHERE substr(day,1,7)=(SELECT month FROM periods WHERE enabled=1) GROUP BY day ORDER BY day'))
                    if not days:raise APIError('No hay fechas de planificación disponibles')
                    db.executemany('INSERT INTO plan(jefe,service,day,kind,p,h,p0,h0) VALUES(?,?,?,?,0,0,0,0)',[(owner,name,r['day'],r['kind']) for r in days])
                    if client is not None:db.execute('INSERT INTO campaign_clients(jefe,service,client) VALUES(?,?,?)',(owner,name,client))
                    admin_log(db,actor,'CREAR_CAMPAÑA',{'name':name,'jefe':owner,'client':client,'days':len(days)});db.commit()
                except BaseException:db.rollback();raise
                return response({'ok':True,'days':len(days)})
            if action=='password':
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                name=payload.get('name');
                if role(name,db)!='jefe':raise APIError('Usuario inválido')
                db.execute('BEGIN IMMEDIATE');db.execute("INSERT INTO users(name,hash,role,must_change) VALUES(?,?,'jefe',0) ON CONFLICT(name) DO UPDATE SET hash=excluded.hash,must_change=0",(name,pw_hash(payload.get('password'))));db.execute('DELETE FROM sessions WHERE actor=?',(name,));admin_log(db,actor,'CONFIGURAR_ACCESO',{'name':name,'role':role(name,db)});db.commit();return response({'ok':True})
            if action in ('absence_save','absence_cancel'):
                if role(actor,db)!='admin':raise APIError('Sin permiso',403)
                return response(manage_absence(db,actor,payload,action=='absence_cancel'))
            if action=='save':return response(save(db,actor,payload.get('changes')))
            raise APIError('Acción desconocida',404)
    except APIError as e:return response({'error':e.message},e.status)
    except Exception as e:
        print('Error interno:',repr(e),file=sys.stderr);return response({'error':'Error interno del servidor'},500)

class ThreadedServer(ThreadingMixIn,WSGIServer):daemon_threads=True
if __name__=='__main__':
    initialize();port=int(os.environ.get('CAT_PORT','8000')); host=os.environ.get('CAT_HOST','127.0.0.1')
    print(f'CAT Planificación: http://{host}:{port}',flush=True)
    with make_server(host,port,application,server_class=ThreadedServer) as server:server.serve_forever()
