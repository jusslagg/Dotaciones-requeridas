"""Export the saved, permission-filtered planning data as a formatted workbook."""
from collections import defaultdict
from datetime import date
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

NAVY='17344F'
TEAL='1C6B72'
WEEKEND='547A90'
HOLIDAY='A25C32'
PALE='DCE6EC'
STRIPE='EDF2F5'
WHITE='FFFFFF'
INK='17344F'

def planning_workbook(rows,display_names=None,export_catalog=None):
    display_names=display_names or {}
    export_catalog=export_catalog or {}
    wb=Workbook()
    ws=wb.active
    ws.title='Planificación'
    ws.freeze_panes='D5'
    ws.sheet_view.showGridLines=False
    ws.column_dimensions['A'].width=26
    ws.column_dimensions['B'].width=20
    ws.column_dimensions['C'].width=38
    days=sorted({r['day'] for r in rows})
    groups=defaultdict(dict)
    day_kinds=defaultdict(set)
    for r in rows:
        groups[(r['jefe'],r['service'])][r['day']]=r
        day_kinds[r['day']].add(r['kind'])
    for i in range(4,max(len(days)+4,12)):
        ws.column_dimensions[get_column_letter(i)].width=10
    def cell(row,col,value,fill=None,bold=False,color=INK,align='center'):
        c=ws.cell(row,col,value)
        if isinstance(value,str):c.data_type='s'
        c.font=Font(name='Calibri',size=10,bold=bold,color=color)
        c.alignment=Alignment(horizontal=align,vertical='center')
        if fill:c.fill=PatternFill('solid',fgColor=fill)
        if row>=2:c.border=Border(left=Side(style='thin',color='C5D5DE'),right=Side(style='thin',color='C5D5DE'),bottom=Side(style='thin',color='DCE6EC'))
        return c
    base=sum(r['p0']*r['h0'] for r in rows)
    projected=sum(r['p']*r['h'] for r in rows)
    for col,label,value in [(1,'Horas objetivo del mes',base),(3,'Horas proyectadas',projected),(6,'Desvío horas',projected-base),(9,'Cumplimiento',projected/base if base else None)]:
        cell(1,col,label,TEAL if col==1 else None,True,WHITE if col==1 else INK,'left')
        if col in (3,6,9):ws.merge_cells(start_row=1,start_column=col,end_row=1,end_column=col+1)
        c=cell(1,col+1 if col==1 else col+2,value,TEAL if col==1 else None,True,WHITE if col==1 else INK)
        c.number_format='0.00%' if col==9 else '#,##0.00'
        if value is None:c.value='—'
    ws.row_dimensions[1].height=25
    names=['Lun','Mar','Mié','Jue','Vie','Sáb','Dom']
    def day_kind(day):
        if 'Fer' in day_kinds[day]:return 'Fer'
        return names[date.fromisoformat(day).weekday()]
    current=2
    for section,field in [('PERSONAS REQUERIDAS','people'),('HORAS OBJETIVO','hours')]:
        last=max(len(days)+3,3)
        cell(current,1,section,TEAL,True,WHITE,'left')
        for col in range(2,last+1):cell(current,col,None,TEAL)
        for col,title in enumerate(('Responsable','Cliente','Campaña'),1):
            cell(current+1,col,title,NAVY,True,WHITE)
            cell(current+2,col,'Día' if col==3 else None,PALE,True)
        for col,day in enumerate(days,4):
            kind=day_kind(day);head=HOLIDAY if kind=='Fer' else WEEKEND if kind in ('Sáb','Dom') else NAVY
            cell(current+1,col,date.fromisoformat(day).strftime('%d/%m'),head,True,WHITE)
            cell(current+2,col,kind,head if head!=NAVY else PALE,True,WHITE if head!=NAVY else INK)
        start=current+3
        for i,((owner,service),by_day) in enumerate(sorted(groups.items())):
            row=start+i;fill=STRIPE if i%2 else WHITE
            client,campaign=export_catalog.get((owner,service),(service.split()[0] if service.split() else '',service))
            cell(row,1,display_names.get(owner,owner),fill,align='left')
            cell(row,2,client,fill,align='left')
            cell(row,3,campaign,fill,align='left')
            for col,day in enumerate(days,4):
                record=by_day.get(day)
                value=(record['p'] if field=='people' else record['p']*record['h']) if record else None
                c=cell(row,col,value,fill);c.number_format='#,##0.00'
        total_row=start+len(groups)
        cell(total_row,1,'TOTAL SITE',NAVY,True,WHITE,'left')
        cell(total_row,2,None,NAVY,True,WHITE)
        cell(total_row,3,None,NAVY,True,WHITE)
        for col,day in enumerate(days,4):
            value=sum((by_day[day]['p'] if field=='people' else by_day[day]['p']*by_day[day]['h']) for by_day in groups.values() if day in by_day)
            c=cell(total_row,col,value,NAVY,True,WHITE);c.number_format='#,##0.00'
        current=total_row+1
    ws.print_options.horizontalCentered=False
    ws.sheet_properties.pageSetUpPr.fitToPage=True
    ws.page_setup.fitToWidth=1
    ws.page_setup.fitToHeight=0
    output=BytesIO();wb.save(output);return output.getvalue()

def summary_workbook(summary,display_names=None):
    display_names=display_names or {}
    wb=Workbook();ws=wb.active;ws.title='Resumen'
    ws.sheet_view.showGridLines=False;ws.freeze_panes='A5'
    ws.merge_cells('A1:E1');ws['A1']='Resumen por campaña'
    ws['A1'].font=Font(name='Calibri',size=15,bold=True,color=WHITE)
    ws['A1'].fill=PatternFill('solid',fgColor=TEAL);ws['A1'].alignment=Alignment(vertical='center')
    ws.row_dimensions[1].height=29
    ws.merge_cells('A2:E2');ws['A2']=f"Mes: {summary['month']}  |  Primer día hábil: {summary['first_business_day'] or 'sin fecha disponible'}"
    for idx,(title,width) in enumerate([('Jefe',26),('Cliente',22),('Campaña',38),('Requerido',16),('Horas',18)],1):
        ws.column_dimensions[get_column_letter(idx)].width=width
        c=ws.cell(4,idx,title);c.font=Font(name='Calibri',bold=True,color=WHITE);c.fill=PatternFill('solid',fgColor=NAVY)
        c.alignment=Alignment(vertical='center')
    ws.row_dimensions[4].height=23
    for rownum,item in enumerate(summary['rows'],5):
        values=[display_names.get(item['jefe'],item['jefe']),item['client'],item['campaign'],item['required'],item['hours']]
        for col,value in enumerate(values,1):
            c=ws.cell(rownum,col,value)
            if isinstance(value,str):c.data_type='s'
            c.font=Font(name='Calibri',size=10,color=INK)
            if rownum%2==0:c.fill=PatternFill('solid',fgColor=STRIPE)
            if col>=4:c.number_format='#,##0.00';c.alignment=Alignment(horizontal='right')
    ws.auto_filter.ref=f'A4:E{max(4,ws.max_row)}'
    output=BytesIO();wb.save(output);return output.getvalue()
