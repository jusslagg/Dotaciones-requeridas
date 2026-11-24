"""Resumen hist?rico de site y comparativo mensual."""
import calendar, json, unicodedata, re
from pathlib import Path
from datetime import date
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from holiday_catalog import official_non_working_days

HISTORY = Path(__file__).resolve().parent / 'seed/site_history_2026.json'

def history():
    return json.loads(HISTORY.read_text(encoding='utf-8'))['months']

def key(value):
    return re.sub(r'[^a-z0-9]+', '', unicodedata.normalize('NFKD',value.casefold()).encode('ascii','ignore').decode())

def previous(month):
    year, m = map(int, month.split('-'))
    return f'{year-1:04d}-12' if m == 1 else f'{year:04d}-{m-1:02d}'

def available(db):
    return sorted(set(history()) | {r[0] for r in db.execute('SELECT month FROM periods')}, reverse=True)

def monthly(db, month, summarize, names):
    archived=history().get(month)
    if archived is not None:
        return {**archived, 'source':'Histórico del Excel', 'historical':True}
    if not db.execute('SELECT 1 FROM periods WHERE month=?',(month,)).fetchone():
        return None
    summary=summarize(db,month); grouped={}
    for row in summary['rows']:
        owner=names.get(row['jefe'],row['jefe']); campaign=row['client'] or row['campaign']
        item=grouped.setdefault((owner,campaign),{'owner':owner,'campaign':campaign,'required':0,'hours':0})
        item['required']+=row['required'] or 0
        item['hours']+=row['hours']
    rows=list(grouped.values())
    return {'rows':rows,'total_required':sum(x['required'] for x in rows),'total_hours':sum(x['hours'] for x in rows),'source':'Planificación guardada, agrupada por cliente','historical':False}

def report(db, month, summarize, names):
    current=monthly(db,month,summarize,names)
    if current is None:return None
    old=monthly(db,previous(month),summarize,names)
    # Historical labels are mapped to the client names used by the current catalog.
    personal_groups={'personalcat','personalcx','personalcgr','personalcobranzas','personalsmb','telecomcobranzas'}
    historical_clients={
        'bbvaseguros':'BBVA', 'openpay':'BBVA OPENPAY',
        'bice':'BANCO BICE', 'getnetargentina':'SANTANDER',
        'santandersl':'SANTANDER', 'supervielleoutbound':'SUPERVIELLE',
        'johnsonjohnson':'JONHSON & JONHSON', 'carrefour':'BSF',
    }
    def by_campaign(rows, historical, period):
        grouped={}
        personal_hours=0
        has_personal=False
        for row in rows:
            name=row['campaign']; group=key(name)
            if group=='personal' or (historical and group in personal_groups):
                group='personal';name='PERSONAL'
                has_personal=True
                if not historical:personal_hours+=row['hours'] or 0
            elif historical and group in historical_clients:
                name=historical_clients[group];group=key(name)
            item=grouped.setdefault(group,{'campaign':name,'required':None})
            if row['required'] is not None:
                item['required']=(item['required'] or 0)+row['required']
        if has_personal and not historical:
            year, month_number=map(int,period.split('-'))
            holidays=official_non_working_days(year) | {r[0] for r in db.execute('SELECT day FROM holidays WHERE substr(day,1,7)=?',(period,))}
            business_days=sum(1 for day in range(1,calendar.monthrange(year,month_number)[1]+1)
                if date(year,month_number,day).weekday()<5 and date(year,month_number,day).isoformat() not in holidays)
            grouped['personal']['required']=personal_hours/(6*business_days) if business_days else None
        return grouped
    old_rows=by_campaign((old or {}).get('rows',[]),(old or {}).get('historical',False),previous(month))
    cur_rows=by_campaign(current['rows'],current['historical'],month)
    changes=[]
    if old:
        for k in sorted(set(old_rows)|set(cur_rows)):
            now=cur_rows.get(k);before=old_rows.get(k)
            a=now.get('required') if now else None;b=before.get('required') if before else None
            if a is None and b is None:continue
            delta=(a or 0)-(b or 0)
            if abs(delta)>1e-9:changes.append({'campaign':(now or before)['campaign'],'required':a,'previous':b,'delta':delta})
    return {'month':month,'previous_month':previous(month),'current':current,'previous':old,'changes':changes,'months':available(db)}

def filter_report(data, owners=(), campaigns=(), front_campaigns=()):
    owners=set(owners);campaigns=set(campaigns);front_campaigns=set(front_campaigns)
    result=dict(data);current=dict(data['current'])
    if owners or campaigns:
        rows=[r for r in current['rows'] if (not owners or r['owner'] in owners) and (not campaigns or r['campaign'] in campaigns)]
        current['rows']=rows
        for field,total in [('required','total_required'),('hours','total_hours')]:
            values=[r[field] for r in rows if r[field] is not None]
            current[total]=sum(values) if values else None
        current['filtered']=True
    result['current']=current
    if front_campaigns:result['changes']=[r for r in data['changes'] if r['campaign'] in front_campaigns]
    return result

def workbook(report):
    w=Workbook();s=w.active;s.title='Resumen site'
    s.append(['Mes',report['month'],'Fuente',report['current']['source']]);s.append(['Responsable','Cliente / campaña','Requerido','Horas objetivo'])
    for r in report['current']['rows']:s.append([r['owner'],r['campaign'],r['required'],r['hours']])
    s.append(['Total filtrado' if report['current'].get('filtered') else 'Total compañía','',report['current']['total_required'],report['current']['total_hours']])
    f=w.create_sheet('Front');f.append(['Mes',report['month'],'Mes anterior',report['previous_month'],'Personal: horas del mes / 6 / días hábiles; histórico según Excel']);f.append(['Cliente','Requerido actual','Requerido anterior','Variación'])
    for r in report['changes']:f.append([r['campaign'],r['required'],r['previous'],r['delta']])
    for sheet in w:
        sheet.freeze_panes='C3';sheet.auto_filter.ref=f'A2:D{max(2,sheet.max_row)}'
        for c in sheet[2]:c.fill=PatternFill('solid',fgColor='17354E');c.font=Font(color='FFFFFF',bold=True)
        for col,width in zip('ABCD',(34,38,22,22)):sheet.column_dimensions[col].width=width
        for row in sheet.iter_rows(min_row=3,min_col=2 if sheet.title=='Front' else 3):
            for cell in row:cell.number_format='#,##0.00'
    b=BytesIO();w.save(b);return b.getvalue()
