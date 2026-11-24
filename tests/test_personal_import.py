import base64,io,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from openpyxl import Workbook
from datetime import datetime,timedelta
from personal_import import PersonalImportError,parse_grid,parse_payload,text_rows,with_responsibles

class PersonalImportTests(unittest.TestCase):
    def table(self):
        dates=['%02d-dic'%i for i in range(1,32)]
        return [['']+['ma.']*31,['']+dates,['ABONOS']+[111,111,99]+[0]*28,['TOTAL MASIVO']+[999]*31]
    def test_markdown_hours_zero_and_totals(self):
        rows=self.table()
        text='\n'.join('| '+' | '.join(map(str,r))+' |' for r in rows)
        data=parse_payload({'month':'2026-12','text':text})
        self.assertEqual(data['campaigns'],1)
        self.assertEqual(data['rows'][0]['days'][0],{'day':'2026-12-01','hours':111})
        self.assertEqual(data['rows'][0]['days'][-1]['hours'],0)
        self.assertEqual(len(data['total_differences']),31)
        self.assertEqual(data['total_differences'][0]['calculated'],111)
    def test_xlsx_numeric_and_sheet_selection(self):
        wb=Workbook();ws=wb.active;ws.title='Personal'
        for row in self.table():ws.append(row)
        b=io.BytesIO();wb.save(b)
        data=parse_payload({'month':'2026-12','file_base64':base64.b64encode(b.getvalue()).decode(),'sheet':'Personal'})
        self.assertEqual(data['rows'][0]['days'][2]['hours'],99)
        with self.assertRaises(PersonalImportError):parse_payload({'month':'2026-12','file_base64':base64.b64encode(b.getvalue()).decode(),'sheet':'Inexistente'})
    def test_invalid_missing_duplicate_and_incorrect_period(self):
        rows=self.table();rows[2][3]=''
        with self.assertRaises(PersonalImportError):parse_grid(rows,'2026-12')
        rows=self.table();rows[1][2]=rows[1][1]
        with self.assertRaises(PersonalImportError):parse_grid(rows,'2026-12')
        with self.assertRaises(PersonalImportError):parse_grid(self.table(),'2026-11')
        rows=self.table();rows[2][1]='-1'
        with self.assertRaises(PersonalImportError):parse_grid(rows,'2026-12')
    def test_localized_values(self):
        rows=self.table();rows[2][1]='4.083';rows[2][2]='12,5'
        data=parse_grid(rows,'2026-12')
        self.assertEqual([r['hours'] for r in data['rows'][0]['days'][:2]],[4083,12.5])
    def test_responsibles_and_division(self):
        data=parse_grid(self.table(),'2026-12')
        data=with_responsibles(data,Path(__file__).resolve().parents[1]/'seed/personal_responsables.json')
        self.assertEqual(data['rows'][0]['suggested_responsibles'],['ANTELO LEMOS, MICAELA SOLEDAD'])
        self.assertEqual(data['rows'][0]['people_first_day'],18.5)
        self.assertEqual(data['rows'][0]['total_hours'],321)
    def test_plp_two_blocks_responsibles_and_missing_source(self):
        wb=Workbook();ws=wb.active
        headers=['Pcia','Site','Responsable','Cliente','Campaña','Subcampaña','Dotación requerida Lunes a Viernes','Horas carga diaria Lunes a Viernes','a','b','c','d','e','f']+[datetime(2026,12,1)+timedelta(days=i) for i in range(31)]+['Horas objetivo mes','Control']
        ws.append(headers)
        ws.append(['BA','Mitre','TEST, RESPONSABLE','PERSONAL','ABONOS','ABONOS',0,6,None,None,None,None,None,None]+[18.5]*31+[0,'OK'])
        ws.append(['BA','Mitre','TEST, RESPONSABLE','PERSONAL','CGR','CGR',0,6,None,None,None,None,None,None]+[None]*31+[0,'PENDIENTE: SIN FUENTE'])
        ws.append([])
        # En el segundo bloque las fechas pueden estar guardadas como números de Excel.
        ws.append(headers[:14]+[46357+i for i in range(31)]+headers[45:])
        ws.append(['BA','Mitre','TEST, RESPONSABLE','PERSONAL','ABONOS','ABONOS',0,6,None,None,None,None,None,None]+[111]*31+[0,'OK'])
        ws.append(['BA','Mitre','TEST, RESPONSABLE','PERSONAL','CGR','CGR',0,6,None,None,None,None,None,None]+[None]*31+[0,'PENDIENTE: SIN FUENTE'])
        b=io.BytesIO();wb.save(b)
        data=with_responsibles(parse_payload({'month':'2026-12','file_base64':base64.b64encode(b.getvalue()).decode()}),Path(__file__).resolve().parents[1]/'seed/personal_responsables.json')
        self.assertEqual((data['format'],data['campaigns'],data['pending_campaigns']),('plp',2,1))
        self.assertEqual(data['rows'][0]['suggested_responsibles'],['TEST, RESPONSABLE'])
        self.assertEqual((data['rows'][0]['days'][0]['hours'],data['rows'][0]['people_first_day']),(111,18.5))
        self.assertIsNone(data['rows'][1]['days'][0]['hours'])
        self.assertTrue(data['rows'][1]['missing_data'])
        self.assertEqual(data['block_differences'],[])
        ws.cell(6,15,120);b=io.BytesIO();wb.save(b)
        data=parse_payload({'month':'2026-12','file_base64':base64.b64encode(b.getvalue()).decode()})
        self.assertEqual(len(data['block_differences']),1)

if __name__=='__main__':unittest.main()
