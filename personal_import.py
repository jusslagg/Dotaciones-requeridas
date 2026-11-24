"""Lectura y validación de la matriz mensual de horas de Personal."""
import base64
import calendar
import csv
import io
import math
import re
import json
import unicodedata
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

class PersonalImportError(ValueError):
    pass

MONTHS={'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,'jul':7,'ago':8,'sep':9,'oct':10,'nov':11,'dic':12}

def _month(value):
    try:
        if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}',value):raise ValueError()
        return date.fromisoformat(value+'-01')
    except ValueError:raise PersonalImportError('Indicá un mes válido.')

def _date(value,month):
    if isinstance(value,datetime):value=value.date()
    if isinstance(value,date):return value if (value.year,value.month)==(month.year,month.month) else None
    if type(value) in (int,float) and 1<=value<=2_958_465:
        try:
            from openpyxl.utils.datetime import from_excel
            converted=from_excel(value)
            if isinstance(converted,datetime):converted=converted.date()
            return converted if isinstance(converted,date) and (converted.year,converted.month)==(month.year,month.month) else None
        except (ValueError,OverflowError):return None
    if not isinstance(value,str):return None
    text=value.strip().lower().replace('.','')
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',text):
            value=date.fromisoformat(text)
            return value if (value.year,value.month)==(month.year,month.month) else None
        m=re.fullmatch(r'(\d{1,2})[-/ ]([a-záéíóú]+|\d{1,2})(?:[-/ ](\d{2,4}))?',text)
        if not m:return None
        day=int(m.group(1));part=m.group(2);actual_month=int(part) if part.isdigit() else MONTHS.get(part[:3])
        year=int(m.group(3)) if m.group(3) else month.year
        if year<100:year+=2000
        if actual_month!=month.month or year!=month.year:return None
        return date(year,actual_month,day)
    except (ValueError,OverflowError):return None

def _hours(value,row,day):
    if isinstance(value,bool) or value is None:raise PersonalImportError(f'Falta un valor de horas para {row}, día {day}.')
    text=str(value).strip().replace('\u00a0','').replace(' ','')
    if not text:raise PersonalImportError(f'Falta un valor de horas para {row}, día {day}.')
    if isinstance(value,str):
        if ',' in text:text=text.replace('.','').replace(',','.')
        elif re.fullmatch(r'\d{1,3}(\.\d{3})+',text):text=text.replace('.','')
    try:number=Decimal(text)
    except InvalidOperation:raise PersonalImportError(f'Valor de horas inválido para {row}, día {day}.')
    if not number.is_finite() or number<0 or number>600000:raise PersonalImportError(f'Valor de horas fuera de rango para {row}, día {day}.')
    return float(number)

def text_rows(text):
    if not isinstance(text,str) or not text.strip():raise PersonalImportError('Pegá o seleccioná una tabla.')
    if len(text)>1_000_000:raise PersonalImportError('La tabla es demasiado grande.')
    lines=[line for line in text.splitlines() if line.strip()]
    if any(line.lstrip().startswith('|') for line in lines):
        rows=[]
        for line in lines:
            if not line.lstrip().startswith('|'):continue
            cells=[c.strip() for c in line.strip().strip('|').split('|')]
            if all(re.fullmatch(r'[:\- ]*',c or '') for c in cells):continue
            rows.append(cells)
        return rows
    delimiter='\t' if any('\t' in line for line in lines[:5]) else ';'
    return list(csv.reader(io.StringIO(text),delimiter=delimiter))

def excel_rows(encoded,sheet=None):
    try:
        raw=base64.b64decode(encoded,validate=True)
        if len(raw)>2_000_000:raise PersonalImportError('El archivo supera el tamaño permitido.')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(x.file_size for x in archive.infolist())>25_000_000:raise PersonalImportError('El archivo descomprimido es demasiado grande.')
        from openpyxl import load_workbook
        wb=load_workbook(io.BytesIO(raw),read_only=True,data_only=True,keep_links=False)
        if sheet and sheet not in wb.sheetnames:raise PersonalImportError('No se encontró la hoja indicada.')
        ws=wb[sheet] if sheet else wb.active
        if (ws.max_row is not None and ws.max_row>2000) or (ws.max_column is not None and ws.max_column>100):raise PersonalImportError('La hoja es demasiado grande.')
        rows=[]
        for row in ws.iter_rows(values_only=True):
            if len(rows)>=2000 or len(row)>100:raise PersonalImportError('La hoja es demasiado grande.')
            rows.append(list(row))
        wb.close();return rows
    except PersonalImportError:raise
    except Exception:raise PersonalImportError('No se pudo leer el Excel. Usá un archivo .xlsx válido.')

def _header_key(value):
    if not isinstance(value,str):return ''
    return ''.join(c for c in unicodedata.normalize('NFKD',value) if not unicodedata.combining(c)).strip().casefold()

def _plp_headers(rows,month,expected):
    found=[]
    for index,row in enumerate(rows):
        columns={_header_key(value):col for col,value in enumerate(row) if isinstance(value,str)}
        required=('pcia','site','responsable','cliente','campana','subcampana')
        if not all(name in columns for name in required):continue
        dates=[(col,_date(value,month)) for col,value in enumerate(row)]
        dates=[(col,day) for col,day in dates if day]
        if len(dates)!=len(expected) or {day for _,day in dates}!=expected:raise PersonalImportError('El archivo PLP debe tener todos los días del mes en ambos bloques.')
        found.append((index,columns,sorted(dates,key=lambda item:item[1])))
    return found

def parse_plp(rows,period,headers):
    if len(headers)!=2:raise PersonalImportError('El archivo PLP debe contener un bloque de dotación y otro de horas.')
    (upper,upcols,updays),(lower,lowcols,lowdays)=headers
    if [day for _,day in updays]!=[day for _,day in lowdays]:raise PersonalImportError('Los días de ambos bloques no coinciden.')
    def value(row,col):return row[col] if col<len(row) else None
    def block(start,end,columns):
        found={}
        for pos in range(start+1,end):
            row=rows[pos]
            name=value(row,columns['campana'])
            if name is None or not str(name).strip():continue
            name=str(name).strip()
            if re.match(r'^total(?:\s|$)',name,flags=re.I):continue
            responsible=str(value(row,columns['responsable']) or '').strip()
            client=str(value(row,columns['cliente']) or '').strip()
            if not responsible or not client:raise PersonalImportError(f'Falta responsable o cliente en la fila {pos+1}.')
            if client.casefold()!='personal':raise PersonalImportError(f'La fila {pos+1} corresponde a otro cliente; esta importación es para PERSONAL.')
            key=(responsible.casefold(),client.casefold(),name.casefold())
            if key in found:raise PersonalImportError(f'La campaña {name} está repetida en un mismo bloque.')
            found[key]=(row,pos+1)
        return found
    top=block(upper,lower,upcols);bottom=block(lower,len(rows),lowcols)
    if not top or set(top)!=set(bottom):raise PersonalImportError('Las campañas de los bloques de dotación y horas no coinciden.')
    result=[];differences=[]
    for key,(hourrow,source_row) in bottom.items():
        personrow,_=top[key]
        name=str(value(hourrow,lowcols['campana'])).strip()
        responsible=str(value(hourrow,lowcols['responsable'])).strip()
        status_col=lowcols.get('control')
        status=str(value(hourrow,status_col) or '').strip() if status_col is not None else ''
        origin_col=lowcols.get('nombre plp')
        origin=str(value(hourrow,origin_col) or '').strip() if origin_col is not None else ''
        durations=[col for heading,col in lowcols.items() if heading=='horas carga diaria lunes a viernes']
        duration=value(hourrow,durations[0]) if durations else None
        if duration is not None and _hours(duration,name,'jornada')!=6:raise PersonalImportError(f'La campaña {name} tiene una jornada distinta de 6 horas; revisala antes de importar.')
        days=[];missing=0
        for (hc,day),(pc,_) in zip(lowdays,updays):
            h=value(hourrow,hc);people=value(personrow,pc)
            if h is None or (isinstance(h,str) and not h.strip()):
                missing+=1;days.append({'day':day.isoformat(),'hours':None});continue
            hours=_hours(h,name,day.day)
            if people is None or (isinstance(people,str) and not people.strip()):
                missing+=1;days.append({'day':day.isoformat(),'hours':hours});continue
            observed=_hours(people,name,day.day)
            if not math.isclose(observed*6,hours,rel_tol=1e-9,abs_tol=1e-6):
                differences.append({'campaign':name,'day':day.isoformat(),'people':observed,'hours':hours})
            days.append({'day':day.isoformat(),'hours':hours})
        missing_data=bool(missing or 'PENDIENTE' in status.upper())
        result.append({'campaign':name,'reference_campaign':name,'source_responsible':responsible,'source_client':'PERSONAL',
                       'source_site':str(value(hourrow,lowcols['site']) or '').strip(),'source_province':str(value(hourrow,lowcols['pcia']) or '').strip(),
                       'source_subcampaign':str(value(hourrow,lowcols['subcampana']) or '').strip(),'source_status':status,'source_origin':origin,'source_row':source_row,
                       'missing_data':missing_data,'missing_days':missing,'days':days})
    return {'month':period,'rows':result,'campaigns':len(result),'days':len(lowdays),'total_differences':[],'format':'plp',
            'block_differences':differences,'pending_campaigns':sum(r['missing_data'] for r in result)}

def parse_grid(rows,period):
    month=_month(period);count=calendar.monthrange(month.year,month.month)[1]
    expected={date(month.year,month.month,d) for d in range(1,count+1)}
    if len(rows)>2000:raise PersonalImportError('La tabla tiene demasiadas filas.')
    headers=_plp_headers(rows,month,expected)
    if headers:return parse_plp(rows,period,headers)
    header=None
    for index,row in enumerate(rows):
        if len(row)>100:raise PersonalImportError('La tabla tiene demasiadas columnas.')
        detected=[(col,_date(value,month)) for col,value in enumerate(row)]
        detected=[(col,day) for col,day in detected if day]
        if len(detected)>=count:
            if len(detected)!=count or {day for _,day in detected}!=expected:raise PersonalImportError('Las fechas deben contener cada día del mes una sola vez.')
            header=(index,sorted(detected,key=lambda item:item[1]));break
    if header is None:raise PersonalImportError('No se encontró una cabecera con todos los días del mes seleccionado.')
    index,dates=header
    if not dates or min(col for col,_ in dates)<1:raise PersonalImportError('Se necesita una columna de campaña antes de las fechas.')
    name_col=min(col for col,_ in dates)-1
    result=[];seen=set();totals=[]
    for row in rows[index+1:]:
        name=str(row[name_col]).strip() if len(row)>name_col and row[name_col] is not None else ''
        if not name:continue
        if re.match(r'^total(?:\s|$)',name,flags=re.I):
            key=' '.join(name.upper().split())
            if key in ('TOTAL MASIVO','TOTAL SMB','TOTAL TECO'):
                totals.append((key,[_hours(row[col] if col<len(row) else None,name,day.day) for col,day in dates]))
            continue
        if len(name)>150:raise PersonalImportError('Hay un nombre de campaña demasiado largo.')
        key=name.casefold()
        if key in seen:raise PersonalImportError(f'La campaña {name} está repetida.')
        seen.add(key)
        values=[{'day':day.isoformat(),'hours':_hours(row[col] if col<len(row) else None,name,day.day)} for col,day in dates]
        result.append({'campaign':name,'days':values})
    if not result:raise PersonalImportError('No se encontraron campañas debajo de las fechas.')
    differences=[]
    for label,values in totals:
        subset=[r for r in result if label=='TOTAL TECO' or (r['campaign'].strip().upper().startswith('SMB -')==(label=='TOTAL SMB'))]
        for i,(_,day) in enumerate(dates):
            calculated=math.fsum(r['days'][i]['hours'] for r in subset)
            if not math.isclose(calculated,values[i],rel_tol=0,abs_tol=1e-6):
                differences.append({'total':label,'day':day.isoformat(),'reported':values[i],'calculated':calculated})
    return {'month':period,'rows':result,'campaigns':len(result),'days':count,'total_differences':differences,'total_checks':len(totals),'format':'hours_matrix'}

def parse_payload(payload):
    rows=excel_rows(payload.get('file_base64',''),payload.get('sheet')) if payload.get('file_base64') else text_rows(payload.get('text',''))
    return parse_grid(rows,payload.get('month'))

def with_responsibles(data,reference_path):
    def key(value):
        value=''.join(c for c in unicodedata.normalize('NFKD',value) if not unicodedata.combining(c))
        return re.sub(r'[^a-z0-9]+',' ',value.lower()).strip()
    reference=json.loads(reference_path.read_text(encoding='utf-8'))
    by_name={key(item['campaign']):item for item in reference}
    aliases={'validaciones':'isla validaciones'}
    for row in data['rows']:
        name=key(row['campaign'])
        item=by_name.get(name) or by_name.get(aliases.get(name,''))
        if row.get('source_responsible'):
            row['suggested_responsibles']=[row['source_responsible']]
        else:
            row['reference_campaign']=item['campaign'] if item else None
            row['suggested_responsibles']=item['responsibles'] if item else []
        first=row['days'][0]['hours']
        row['people_first_day']=first/6 if first is not None else None
        row['total_hours']=math.fsum(day['hours'] for day in row['days'] if day['hours'] is not None)
    return data
