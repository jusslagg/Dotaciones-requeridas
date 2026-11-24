import io,json,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as s
from openpyxl import load_workbook

class TestApi(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=s.DATA;s.DATA=Path(self.tmp.name);s.initialize();self.cookies={}
    def tearDown(self):s.DATA=self.old;self.tmp.cleanup()
    def call(self,action,payload=None,client='admin',expected=200):
        body=json.dumps(payload or {}).encode();env={'REQUEST_METHOD':'GET' if payload is None else 'POST','QUERY_STRING':'api='+action,'PATH_INFO':'/','CONTENT_LENGTH':str(len(body)),'wsgi.input':io.BytesIO(body),'HTTP_COOKIE':self.cookies.get(client,''),'wsgi.url_scheme':'http'}; result={}
        def start(status,headers):
            result['status']=int(status.split()[0]);
            for key,value in headers:
                if key=='Set-Cookie':self.cookies[client]=value.split(';')[0]
        data=json.loads(b''.join(s.application(env,start)));self.assertEqual(result['status'],expected,data);return data
    def login(self,client,name,password):
        status=self.call('status',client=client);self.call('login',{'name':name,'password':password,'csrf':status['csrf']},client);return self.call('status',client=client)['csrf']
    def test_personal_previews_replace_without_modifying_planning(self):
        st=self.call('status');self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':'Password-admin-test!'})
        admin=self.login('admin','admin','Password-admin-test!')
        chief=self.login('chief','Carolina','Carolina');self.call('change_password',{'csrf':chief,'password':'12345678'},'chief')
        self.call('personal_draft&month=2026-12',client='chief',expected=403)
        text='Campaña\t'+'\t'.join('%02d-dic'%d for d in range(1,32))+'\nABONOS\t'+'\t'.join(['111']*31)
        payload={'csrf':admin,'month':'2026-12','text':text}
        self.call('personal_preview',{**payload,'csrf':chief},'chief',403)
        p=self.call('personal_preview',payload)
        self.assertEqual(p['rows'][0]['people_first_day'],18.5)
        self.assertEqual(p['rows'][0]['suggested_responsibles'],['ANTELO LEMOS, MICAELA SOLEDAD'])
        before=self.call('data')['plan']
        first=self.call('personal_save',payload)['id']
        second=self.call('personal_save',{**payload,'text':text.replace('111','0')})['id']
        self.assertGreater(second,first)
        draft=self.call('personal_draft&month=2026-12')['draft']
        self.assertEqual(draft['id'],second)
        self.assertEqual(draft['data']['rows'][0]['days'][0]['hours'],0)
        self.assertEqual(self.call('data')['plan'],before)
        with s.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM personal_import_versions').fetchone()[0],2)
    def test_publish_personal_preserves_baseline_and_requires_review(self):
        st=self.call('status');self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':'Password-admin-test!'})
        admin=self.login('admin','admin','Password-admin-test!')
        head='Campaña\t'+'\t'.join('%02d-dic'%d for d in range(1,32))
        make=lambda v:head+'\nABONOS\t'+'\t'.join([str(v)]*31)+'\nDetractores\t'+'\t'.join(['0']*31)
        one=self.call('personal_save',{'csrf':admin,'month':'2026-12','text':make(111)})['id']
        suggest='ANTELO LEMOS, MICAELA SOLEDAD'
        choices=[{'name':suggest,'create':True},{'name':'','create':False}]
        self.call('personal_publish',{'csrf':admin,'id':one,'assignments':choices},expected=400)
        with s.connect() as db:self.assertIsNone(db.execute('SELECT 1 FROM users WHERE name=?',(suggest,)).fetchone())
        choices[1]={'name':suggest,'create':True}
        result=self.call('personal_publish',{'csrf':admin,'id':one,'assignments':choices})
        self.assertEqual(result['inserted'],62)
        data=self.call('data&month=2026-12')['plan']
        row=next(r for r in data if r['service']=='ABONOS' and r['day']=='2026-12-01')
        self.assertEqual((row['p'],row['h'],row['p0'],row['h0'],row['client']),(18.5,6,18.5,6,'PERSONAL'))
        two=self.call('personal_save',{'csrf':admin,'month':'2026-12','text':make(0)})['id']
        self.call('personal_publish',{'csrf':admin,'id':one,'assignments':choices},expected=409)
        result=self.call('personal_publish',{'csrf':admin,'id':two,'assignments':choices})
        self.assertEqual(result['updated'],31)
        row=next(r for r in self.call('data&month=2026-12')['plan'] if r['service']=='ABONOS' and r['day']=='2026-12-01')
        self.assertEqual((row['p'],row['h'],row['p0'],row['h0']),(0,6,18.5,6))
        self.assertEqual(len([a for a in self.call('data&month=2026-12')['audit'] if a['service']=='ABONOS']),31)
    def test_plp_import_skips_missing_and_rejects_inconsistent_blocks(self):
        import base64
        from datetime import datetime,timedelta
        from openpyxl import Workbook
        st=self.call('status');self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':'Password-admin-test!'})
        admin=self.login('admin','admin','Password-admin-test!')
        wb=Workbook();ws=wb.active
        headers=['Pcia','Site','Responsable','Cliente','Campaña','Subcampaña','Dotación requerida Lunes a Viernes','Horas carga diaria Lunes a Viernes','a','b','c','d','e','f']+[datetime(2026,12,1)+timedelta(days=i) for i in range(31)]+['Horas objetivo mes','Control']
        owner='ANTELO LEMOS, MICAELA SOLEDAD'
        ws.append(headers)
        ws.append(['BA','Mitre',owner,'PERSONAL','ABONOS','ABONOS',0,6,None,None,None,None,None,None]+[18.5]*31+[0,'OK'])
        ws.append(['BA','Mitre',owner,'PERSONAL','CGR','CGR',0,6,None,None,None,None,None,None]+[None]*31+[0,'PENDIENTE: SIN FUENTE'])
        ws.append([]);ws.append(headers)
        ws.append(['BA','Mitre',owner,'PERSONAL','ABONOS','ABONOS',0,6,None,None,None,None,None,None]+[111]*31+[0,'OK'])
        ws.append(['BA','Mitre',owner,'PERSONAL','CGR','CGR',0,6,None,None,None,None,None,None]+[None]*31+[0,'PENDIENTE: SIN FUENTE'])
        def payload():
            b=io.BytesIO();wb.save(b)
            return {'csrf':admin,'month':'2026-12','file_base64':base64.b64encode(b.getvalue()).decode()}
        preview=self.call('personal_preview',payload())
        self.assertEqual((preview['format'],preview['pending_campaigns']),('plp',1))
        self.assertEqual(preview['rows'][0]['people_first_day'],18.5)
        self.assertIsNone(preview['rows'][1]['days'][0]['hours'])
        version=self.call('personal_save',payload())['id']
        choices=[{'name':'Carolina','create':False},{'name':'','create':False}]
        result=self.call('personal_publish',{'csrf':admin,'id':version,'assignments':choices})
        self.assertEqual((result['inserted'],result['pending_campaigns']),(31,['CGR']))
        self.assertFalse(any(r['service']=='CGR' for r in self.call('data')['plan']))
        with s.connect() as db:
            details=db.execute('SELECT province,site,subcampaign FROM campaign_details WHERE jefe=? AND service=?',('Carolina','ABONOS')).fetchone()
            self.assertEqual(tuple(details),('BA','Mitre','ABONOS'))
        ws.cell(6,15,120)
        version=self.call('personal_save',payload())['id']
        self.call('personal_publish',{'csrf':admin,'id':version,'assignments':choices},expected=409)
        # La siguiente carga no borra una campaña sin fuente y sí incorpora ceros explícitos.
        ws.cell(2,15,None);ws.cell(2,15).value=None
        ws.cell(6,15,None);ws.cell(6,15).value=None
        ws.cell(2,47,'PENDIENTE: SIN FUENTE');ws.cell(6,47,'PENDIENTE: SIN FUENTE')
        for col in range(15,46):
            ws.cell(3,col,0);ws.cell(7,col,0)
        ws.cell(3,47,'OK');ws.cell(7,47,'OK')
        version=self.call('personal_save',payload())['id']
        result=self.call('personal_publish',{'csrf':admin,'id':version,'assignments':[{'name':'','create':False},{'name':'Carolina','create':False}]})
        self.assertEqual((result['inserted'],result['pending_campaigns']),(31,['ABONOS']))
        rows=self.call('data')['plan']
        self.assertEqual(next(r for r in rows if r['service']=='ABONOS' and r['day']=='2026-12-01')['p'],18.5)
        zero=next(r for r in rows if r['service']=='CGR' and r['day']=='2026-12-01')
        self.assertEqual((zero['p'],zero['h']),(0,6))
    def test_campaign_name_case_change_preserves_client_and_revisions(self):
        st=self.call('status');self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':'Password-admin-test!'})
        admin=self.login('admin','admin','Password-admin-test!')
        before=next(r for r in self.call('data')['plan'] if r['jefe']=='Carolina' and r['service']=='Spazios')
        self.call('rename_campaign',{'csrf':admin,'jefe':'Carolina','name':'Spazios','new_name':'SPAZIOS'})
        after=next(r for r in self.call('data')['plan'] if r['id']==before['id'])
        self.assertEqual((after['service'],after['client'],after['rev']),('SPAZIOS','SPAZIOS',before['rev']+1))
        self.assertEqual((after['p'],after['h'],after['p0'],after['h0']),(before['p'],before['h'],before['p0'],before['h0']))
        self.call('save',{'csrf':admin,'changes':[{'id':before['id'],'rev':before['rev'],'p':before['p']+1,'h':before['h']}]},expected=409)
        row=next(r for r in self.call('admin_summary')['rows'] if r['jefe']=='Carolina' and r['campaign']=='SPAZIOS')
        self.assertEqual(row['client'],'SPAZIOS')
    def test_explicit_client_survives_renames_and_controls_summary(self):
        st=self.call('status');self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':'Password-admin-test!'})
        admin=self.login('admin','admin','Password-admin-test!')
        self.call('create_campaign',{'csrf':admin,'name':'SMB - Inbound','jefe':'Carolina','client':'PERSONAL'})
        row=next(r for r in self.call('admin_summary')['rows'] if r['campaign']=='SMB - Inbound')
        self.assertEqual(row['client'],'PERSONAL')
        self.assertTrue(all(r['p']==0 and r['h']==0 for r in self.call('data')['plan'] if r['service']=='SMB - Inbound'))
        self.call('set_campaign_client',{'csrf':admin,'jefe':'Carolina','service':'SMB - Inbound','client':'PERSONAL ARGENTINA'})
        self.call('rename_campaign',{'csrf':admin,'jefe':'Carolina','name':'SMB - Inbound','new_name':'SMB - Digital'})
        self.call('rename_user',{'csrf':admin,'name':'Carolina','new_name':'Nuevo Jefe'})
        row=next(r for r in self.call('admin_summary')['rows'] if r['campaign']=='SMB - Digital')
        self.assertEqual((row['jefe'],row['client']),('Nuevo Jefe','PERSONAL ARGENTINA'))
        s.initialize()
        self.assertEqual(next(r for r in self.call('admin_summary')['rows'] if r['campaign']=='SMB - Digital')['client'],'PERSONAL ARGENTINA')
    def test_full_names_migrate_without_changing_accounts(self):
        with s.connect() as db:
            db.execute("DELETE FROM settings WHERE key='chief_full_names_initialized'")
            for name,old in s.PREVIOUS_DISPLAY.items():
                db.execute('UPDATE users SET display_name=? WHERE name=?',(old,name))
            before={r['name']:r['hash'] for r in db.execute("SELECT name,hash FROM users WHERE role='jefe'")}
        s.initialize()
        with s.connect() as db:
            names=s.display_names(db)
            after={r['name']:r['hash'] for r in db.execute("SELECT name,hash FROM users WHERE role='jefe'")}
        self.assertEqual({k:names[k] for k in s.DEFAULT_DISPLAY},s.DEFAULT_DISPLAY)
        self.assertEqual(before,after)
        with s.connect() as db:db.execute("UPDATE users SET display_name='Nombre personalizado' WHERE name='Carolina'")
        s.initialize()
        with s.connect() as db:self.assertEqual(s.display_names(db)['Carolina'],'Nombre personalizado')
    def excel(self,client,owner='Todas'):
        from urllib.parse import urlencode
        env={'REQUEST_METHOD':'GET','QUERY_STRING':urlencode({'api':'export_excel','jefe':owner}),'PATH_INFO':'/','CONTENT_LENGTH':'0','wsgi.input':io.BytesIO(b''),'HTTP_COOKIE':self.cookies.get(client,''),'wsgi.url_scheme':'http'};result={}
        def start(status,headers):result.update(status=int(status.split()[0]),headers=dict(headers))
        body=b''.join(s.application(env,start))
        return result,body
    def summary_excel(self,browser_client,**filters):
        from urllib.parse import urlencode
        env={'REQUEST_METHOD':'GET','QUERY_STRING':urlencode({'api':'export_summary',**filters},doseq=True),'PATH_INFO':'/','CONTENT_LENGTH':'0','wsgi.input':io.BytesIO(b''),'HTTP_COOKIE':self.cookies.get(browser_client,''),'wsgi.url_scheme':'http'};result={}
        def start(status,headers):result.update(status=int(status.split()[0]),headers=dict(headers))
        return result,b''.join(s.application(env,start))
    def test_summary_excel_filters_and_permissions(self):
        st=self.call('status');self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':'Password-admin-test!'})
        self.login('admin','admin','Password-admin-test!')
        chief=self.login('chief','Carolina','Carolina');self.call('change_password',{'csrf':chief,'password':'12345678'},'chief')
        self.assertEqual(self.summary_excel('chief')[0]['status'],403)
        summary=self.call('admin_summary');row=next(r for r in summary['rows'] if r['jefe']=='Carolina')
        result,body=self.summary_excel('admin',chief=row['jefe'],client=row['client'],campaign=row['campaign'])
        self.assertEqual(result['status'],200)
        ws=load_workbook(io.BytesIO(body),data_only=True).active
        expected=[r for r in summary['rows'] if (r['jefe'],r['client'],r['campaign'])==(row['jefe'],row['client'],row['campaign'])]
        self.assertEqual(ws.max_row,4+len(expected))
        self.assertEqual(ws['A5'].value,'SURACE, CAROLINA VICTORIA')
        self.assertEqual(ws['C5'].value,row['campaign'])
        self.assertEqual(ws['D5'].value,row['required'])
        self.assertAlmostEqual(ws['E5'].value,row['hours'])
        chiefs=['Carolina','Ismael']
        result,body=self.summary_excel('admin',chief=chiefs)
        ws=load_workbook(io.BytesIO(body),data_only=True).active
        self.assertEqual(ws.max_row,4+sum(r['jefe'] in chiefs for r in summary['rows']))
        self.assertEqual({ws.cell(i,1).value for i in range(5,ws.max_row+1)},{'SURACE, CAROLINA VICTORIA','RISSI PEREIRA, ISMAEL NICOLAS'})
    def test_holidays_mark_restore_and_future_month(self):
        st=self.call('status');self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':'Password-admin-test!'})
        admin=self.login('admin','admin','Password-admin-test!')
        chief=self.login('chief','Carolina','Carolina');self.call('change_password',{'csrf':chief,'password':'12345678'},'chief')
        self.call('holidays&year=2027',client='chief',expected=403)
        calendar=self.call('holidays&year=2027')
        self.assertTrue(any(r['day']=='2027-01-01' for r in calendar['official']))
        self.call('holiday_mark',{'csrf':chief,'day':'2026-12-01','name':'Actividad','source':'custom'},'chief',403)
        before=self.call('data')['plan'];row=next(r for r in before if r['day']=='2026-12-01')
        result=self.call('holiday_mark',{'csrf':admin,'day':'2026-12-01','name':'Actividad especial','source':'custom'})
        self.assertGreater(result['records'],0)
        current=next(r for r in self.call('data')['plan'] if r['id']==row['id'])
        self.assertEqual(current['kind'],'Fer')
        self.assertEqual((current['p'],current['h'],current['p0'],current['h0']),(row['p'],row['h'],row['p0'],row['h0']))
        self.assertEqual(current['rev'],row['rev']+1)
        self.assertEqual(self.call('admin_summary')['first_business_day'],'2026-12-02')
        self.call('save',{'csrf':admin,'changes':[{'id':row['id'],'rev':row['rev'],'p':row['p']+1,'h':row['h']}]},expected=409)
        self.call('holiday_remove',{'csrf':admin,'day':'2026-12-01'})
        self.assertEqual(self.call('admin_summary')['first_business_day'],'2026-12-01')
        self.call('holiday_mark',{'csrf':admin,'day':'2027-01-01','source':'official'})
        self.call('holiday_mark',{'csrf':admin,'day':'2027-01-02','source':'official'},expected=400)
        self.call('open_month',{'csrf':admin,'month':'2027-01','mode':'weekday'})
        january=self.call('data')['plan']
        self.assertTrue(all(r['kind']=='Fer' for r in january if r['day']=='2027-01-01'))
        self.assertEqual(self.call('admin_summary')['first_business_day'],'2027-01-04')
        self.call('holiday_remove',{'csrf':admin,'day':'2027-01-01'})
        self.assertEqual(self.call('admin_summary')['first_business_day'],'2027-01-04')
        s.initialize()
        self.assertFalse(any(r['day']=='2027-01-01' for r in self.call('holidays&year=2027')['marked']))
    def test_admin_summary_first_workday_and_clients(self):
        st=self.call('status');self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':'Password-admin-test!'})
        admin=self.login('admin','admin','Password-admin-test!')
        self.assertEqual(self.call('status')['display_names']['Carolina'],'SURACE, CAROLINA VICTORIA')
        chief=self.login('chief','Carolina','Carolina')
        self.call('change_password',{'csrf':chief,'password':'12345678'},'chief')
        self.call('admin_summary',client='chief',expected=403)
        data=self.call('data')['plan'];row=next(r for r in data if r['jefe']=='Carolina' and r['day']=='2026-12-01')
        summary=self.call('admin_summary')
        self.assertEqual(summary['first_business_day'],'2026-12-01')
        result=next(r for r in summary['rows'] if r['jefe']=='Carolina' and r['campaign']==row['service'])
        self.assertEqual(result['client'],row['client'])
        self.assertEqual(result['client'],'ASSURANT')
        self.assertEqual(result['required'],row['p'])
        self.assertAlmostEqual(result['hours'],sum(r['p']*r['h'] for r in data if r['jefe']=='Carolina' and r['service']==row['service']))
        with s.connect() as db:db.execute("UPDATE plan SET kind='Fer' WHERE day='2026-12-01'")
        self.assertEqual(self.call('admin_summary')['first_business_day'],'2026-12-02')
        self.call('rename_campaign',{'csrf':admin,'jefe':'Carolina','name':row['service'],'new_name':'Campaña nueva'})
        self.call('rename_user',{'csrf':admin,'name':'Carolina','new_name':'Otro Usuario'})
        result=next(r for r in self.call('admin_summary')['rows'] if r['jefe']=='Otro Usuario' and r['campaign']=='Campaña nueva')
        self.assertEqual(result['client'],'ASSURANT')
    def test_period_open_and_permissions(self):
        st=self.call('status');self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':'Password-admin-test!'})
        admin=self.login('admin','admin','Password-admin-test!')
        chief=self.login('chief','Carolina','Carolina')
        self.call('change_password',{'csrf':chief,'password':'12345678'},'chief')
        before=self.call('data',client='chief')['plan']
        self.call('open_month',{'csrf':chief,'month':'2027-01','mode':'weekday'},'chief',403)
        self.call('open_month',{'csrf':admin,'month':'2027-02','mode':'weekday'},expected=409)
        self.call('open_month',{'csrf':admin,'month':'2027-01','mode':'weekday'})
        self.call('open_month',{'csrf':admin,'month':'2027-01','mode':'weekday'},expected=409)
        self.call('data&month=2026-12',client='chief',expected=403)
        self.call('save',{'csrf':chief,'changes':[{'id':before[0]['id'],'rev':before[0]['rev'],'p':10,'h':8}]},'chief',403)
        january=self.call('data',client='chief')['plan']
        sample=next(r for r in january if r['day']=='2027-01-04')
        old=next(r for r in before if r['service']==sample['service'] and r['day']=='2026-12-28')
        self.assertEqual((sample['p'],sample['h'],sample['p0'],sample['h0']),(old['p'],old['h'],old['p'],old['h']))
        self.assertEqual(len(january),len(before))
        self.assertEqual(len(self.call('data&month=2026-12')['plan']),1829)
        self.call('open_month',{'csrf':admin,'month':'2027-02','mode':'weekday'})
        feb=self.call('data',client='chief')['plan']
        self.assertEqual(len(feb),len(before)//31*28)
        self.call('enable_month',{'csrf':admin,'month':'2026-12'})
        self.assertEqual(self.call('data',client='chief')['month'],'2026-12')
    def test_rename_preserves_permissions_and_audit(self):
        st=self.call('status');self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':'Password-admin-test!'})
        admin=self.login('admin','admin','Password-admin-test!')
        chief=self.login('chief','Carolina','Carolina')
        self.call('change_password',{'csrf':chief,'password':'12345678'},'chief')
        row=self.call('data',client='chief')['plan'][0]
        self.call('save',{'csrf':chief,'changes':[{'id':row['id'],'rev':row['rev'],'p':row['p']+1,'h':row['h']}]},'chief')
        before_rename=next(r for r in self.call('data',client='chief')['plan'] if r['id']==row['id'])
        self.call('rename_campaign',{'csrf':admin,'jefe':'Carolina','name':row['service'],'new_name':'Nueva Campaña'})
        self.call('save',{'csrf':chief,'changes':[{'id':row['id'],'rev':before_rename['rev'],'p':before_rename['p']+1,'h':row['h']}]},'chief',409)
        self.call('rename_user',{'csrf':admin,'name':'Carolina','new_name':'Nuevo Nombre'})
        self.assertIsNone(self.call('status',client='chief')['actor'])
        self.login('chief','Nuevo Nombre','12345678')
        data=self.call('data',client='chief')
        self.assertTrue(any(r['service']=='Nueva Campaña' and r['jefe']=='Nuevo Nombre' for r in data['plan']))
        self.assertEqual(data['audit'][0]['service'],'Nueva Campaña')
        self.assertEqual(data['audit'][0]['actor'],'Carolina')
        with s.connect() as db:
            mapped=s.export_catalog(db).get(('Nuevo Nombre','Nueva Campaña'))
            self.assertEqual(mapped,('ASSURANT','Nueva Campaña'))
        s.initialize()
        self.assertNotIn('Carolina',self.call('status')['names'])
        self.assertEqual(len(self.call('data',client='chief')['audit']),1)
    def test_excel_export(self):
        st=self.call('status');self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':'Password-admin-test!'})
        self.login('admin','admin','Password-admin-test!')
        csrf=self.login('chief','Carolina','Carolina')
        self.call('change_password',{'csrf':csrf,'password':'12345678'},'chief')
        result,body=self.excel('chief')
        self.assertEqual(result['status'],200)
        self.assertIn('spreadsheetml',result['headers']['Content-Type'])
        ws=load_workbook(io.BytesIO(body),data_only=True).active
        self.assertEqual(ws['A2'].value,'PERSONAS REQUERIDAS')
        self.assertEqual([ws.cell(3,i).value for i in range(1,5)],['Responsable','Cliente','Campaña','01/12'])
        self.assertEqual(ws['D4'].value,'Mar')
        plan=self.call('data',client='chief')['plan']
        self.assertAlmostEqual(ws['B1'].value,sum(r['p0']*r['h0'] for r in plan))
        self.assertAlmostEqual(ws['E1'].value,sum(r['p']*r['h'] for r in plan))
        self.assertIn('HORAS OBJETIVO',[ws.cell(i,1).value for i in range(1,ws.max_row+1)])
        self.assertEqual(ws['A5'].value,'SURACE, CAROLINA VICTORIA')
        self.assertEqual(ws['B5'].value,'ASSURANT')
        self.assertEqual(ws['C5'].value,'BBVA DESEMPLEO')
        self.assertEqual(ws['D5'].number_format,'#,##0.00')
        self.assertEqual(ws['D3'].border.right.style,'thin')
        self.assertEqual(ws['D5'].border.right.style,'thin')
        self.assertEqual(ws.freeze_panes,'D5')
        hours_heading=next(i for i in range(1,ws.max_row+1) if ws.cell(i,1).value=='HORAS OBJETIVO')
        self.assertEqual([ws.cell(hours_heading+1,i).value for i in range(1,5)],['Responsable','Cliente','Campaña','01/12'])
        self.assertEqual([ws.cell(hours_heading+3,i).value for i in range(1,4)],[ws.cell(5,i).value for i in range(1,4)])
        filtered_result,filtered_body=self.excel('chief','Ismael')
        self.assertEqual(filtered_result['status'],200)
        filtered=load_workbook(io.BytesIO(filtered_body),data_only=True).active
        self.assertAlmostEqual(filtered['E1'].value,sum(r['p']*r['h'] for r in plan))
        result,body=self.excel('admin','Ismael')
        self.assertEqual(result['status'],200)
        ws=load_workbook(io.BytesIO(body),data_only=True).active
        allowed=self.call('data')['plan']
        self.assertAlmostEqual(ws['E1'].value,sum(r['p']*r['h'] for r in allowed))
        records=[tuple(ws.cell(i,c).value for c in range(1,4)) for i in range(5,5+len({(r['jefe'],r['service']) for r in allowed}))]
        self.assertIn(('LOPEZ DE LA VEGA, ROXANA','SANTANDER','GETNET STANDARD'),records)
    def test_create_chief_and_campaign(self):
        st=self.call('status');self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':'Password-admin-test!'})
        admin=self.login('admin','Admin','Password-admin-test!')
        self.call('create_jefe',{'csrf':admin,'name':'Nuevo'})
        self.call('create_jefe',{'csrf':admin,'name':'nuevo'},expected=409)
        self.call('create_campaign',{'csrf':admin,'name':'Campaña nueva','jefe':'Nuevo'})
        self.call('create_campaign',{'csrf':admin,'name':'campaña nueva','jefe':'Nuevo'},expected=409)
        self.call('create_campaign',{'csrf':admin,'name':'Inválida','jefe':'admin'},expected=400)
        chief=self.login('new','Nuevo','Nuevo')
        self.call('change_password',{'csrf':chief,'password':'12345678'},'new')
        rows=self.call('data',client='new')['plan']
        self.assertEqual(len(rows),31)
        self.assertTrue(all(r['jefe']=='Nuevo' and r['service']=='Campaña nueva' and r['p']==0 and r['h']==0 for r in rows))
        self.call('create_jefe',{'csrf':chief,'name':'Intruso'},'new',403)
        self.call('create_campaign',{'csrf':chief,'name':'Intrusa','jefe':'Nuevo'},'new',403)
        day=s.today()
        absence=self.call('absence_save',{'csrf':admin,'jefe':'Nuevo','start':day,'end':day,'reason':'Vacaciones','assignments':{'Campaña nueva':'Carolina'}})
        self.assertEqual(self.call('data',client='new')['plan'],[])
        carolina=self.login('carolina','Carolina','Carolina')
        self.call('change_password',{'csrf':carolina,'password':'12345678'},'carolina')
        self.assertEqual(len([r for r in self.call('data',client='carolina')['plan'] if r['jefe']=='Nuevo']),31)
        self.call('absence_cancel',{'csrf':admin,'id':absence['id']})
        s.initialize()
        self.assertEqual(len(self.call('data',client='new')['plan']),31)
    def test_initial_password_and_extra_admin(self):
        st=self.call('status'); self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':'Password-admin-test!'})
        admin=self.login('admin','admin','Password-admin-test!')
        chief=self.login('chief','Carolina','Carolina')
        self.assertTrue(self.call('status',client='chief')['must_change'])
        self.call('data',client='chief',expected=403)
        self.call('change_password',{'csrf':chief,'password':'abc12345'},'chief',400)
        self.call('change_password',{'csrf':chief,'password':'12345678'},'chief')
        self.assertFalse(self.call('status',client='chief')['must_change'])
        self.assertTrue(all(r['jefe']=='Carolina' for r in self.call('data',client='chief')['plan']))
        self.call('create_admin',{'csrf':chief,'name':'other','password':'Password-admin-test!'},'chief',403)
        self.call('create_admin',{'csrf':admin,'name':'other','password':'Password-admin-test!'})
        other=self.login('other','other','Password-admin-test!')
        self.assertEqual(self.call('status',client='other')['role'],'admin')
        self.assertEqual(len(self.call('data',client='other')['plan']),1829)
        self.call('password',{'csrf':other,'name':'Ismael','password':'Password-jefe-test!'},'other')
        self.assertEqual(self.call('management',client='other')['events'][0]['actor'],'other')
        s.initialize()
        self.assertFalse(self.call('status',client='chief')['must_change'])
    def test_full_workflow(self):
        st=self.call('status');self.assertTrue(st['setup']);pw='Password-admin-test!';self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':pw});csrf=self.login('admin','admin',pw)
        data=self.call('data');self.assertEqual(len(data['plan']),1829);self.assertEqual(len({(r['jefe'],r['service']) for r in data['plan']}),59)
        self.call('password',{'csrf':csrf,'name':'Carolina','password':'Password-jefe-test!'});cc=self.login('jefe','Carolina','Password-jefe-test!');mine=self.call('data',client='jefe')['plan'];self.assertTrue(all(r['jefe']=='Carolina' for r in mine));r=mine[0];other=next(x for x in data['plan'] if x['jefe']!='Carolina')
        def change(row,p=None,h=None):return {'id':row['id'],'rev':row['rev'],'p':row['p'] if p is None else p,'h':row['h'] if h is None else h}
        self.call('save',{'csrf':cc,'changes':[change(r,r['p']+1),change(other,other['p']+1)]},'jefe',403);self.assertEqual(self.call('data',client='jefe')['audit'],[])
        self.call('save',{'csrf':cc,'changes':[change(r,r['p']+1)]},'jefe');self.call('save',{'csrf':cc,'changes':[change(r,r['p']+2)]},'jefe',409)
        fresh=self.call('data',client='jefe');new=next(x for x in fresh['plan'] if x['id']==r['id']);self.call('save',{'csrf':cc,'changes':[change(new,r['p'])]},'jefe');self.assertEqual(len(self.call('data',client='jefe')['audit']),2)
        s.initialize();self.assertEqual(len(self.call('data')['audit']),2)
        campaign=[x for x in self.call('data',client='jefe')['plan'] if x['service']==r['service']];self.assertEqual(len(campaign),31);self.call('save',{'csrf':cc,'changes':[change(x,x['p']+1) for x in campaign]},'jefe');audit=self.call('data')['audit'];self.assertEqual(len(audit),33);self.assertEqual(len({x['batch'] for x in audit[:31]}),1)
        self.call('password',{'csrf':cc,'name':'Roxana','password':'Password-other-test!'},'jefe',403);self.call('save',{'csrf':'invalid','changes':[]},'jefe',403)
        with s.connect() as db:
            with self.assertRaises(Exception):db.execute('DELETE FROM audit')
    def test_vacation_coverage(self):
        from datetime import date,timedelta
        from unittest.mock import patch
        day=date.fromisoformat(s.today()); end=(day+timedelta(days=4)).isoformat(); start=day.isoformat()
        st=self.call('status');pw='Password-admin-test!';self.call('setup',{'csrf':st['csrf'],'key':(s.DATA/'setup.key').read_text(),'password':pw});a=self.login('admin','admin',pw)
        for name in ('Carolina','Ismael','Mariela'):
            self.call('password',{'csrf':a,'name':name,'password':'Password-jefe-test!'})
        c=self.login('carolina','Carolina','Password-jefe-test!');i=self.login('ismael','Ismael','Password-jefe-test!');m=self.login('mariela','Mariela','Password-jefe-test!')
        original=self.call('data',client='carolina')['plan'];services=list(dict.fromkeys(r['service'] for r in original));first,second=services[:2]
        self.call('management',client='ismael',expected=403)
        payload={'csrf':a,'jefe':'Carolina','start':start,'end':end,'reason':'Vacaciones','assignments':{first:'Ismael',second:'Mariela'}}
        aid=self.call('absence_save',payload)['id'];self.assertEqual(self.call('data',client='carolina')['plan'],[])
        ismael=self.call('data',client='ismael')['plan'];self.assertEqual({r['service'] for r in ismael if r['jefe']=='Carolina'},{first})
        mariela=self.call('data',client='mariela')['plan'];self.assertEqual({r['service'] for r in mariela if r['jefe']=='Carolina'},{second})
        def change(r):return {'id':r['id'],'rev':r['rev'],'p':r['p']+1,'h':r['h']}
        row=next(r for r in ismael if r['jefe']=='Carolina');other=next(r for r in original if r['service']==second)
        self.call('save',{'csrf':i,'changes':[change(other)]},'ismael',403)
        self.call('save',{'csrf':c,'changes':[change(row)]},'carolina',403)
        self.call('save',{'csrf':i,'changes':[change(row)]},'ismael');self.assertEqual(self.call('data')['audit'][0]['actor'],'Ismael');self.assertEqual(self.call('data')['audit'][0]['jefe'],'Carolina')
        self.call('absence_save',{**payload,'csrf':i},'ismael',403)
        self.call('absence_save',payload,expected=409)
        self.call('absence_save',{**payload,'jefe':'Ismael','assignments':{}},expected=409)
        self.call('absence_save',{**payload,'id':aid,'assignments':{first:'Mariela',second:'Mariela'}})
        self.assertFalse(any(r['jefe']=='Carolina' for r in self.call('data',client='ismael')['plan']))
        with patch.object(s,'today',return_value=(day+timedelta(days=5)).isoformat()):
            self.assertEqual(len(self.call('data',client='carolina')['plan']),len(original));self.assertFalse(any(r['jefe']=='Carolina' for r in self.call('data',client='mariela')['plan']))
        self.call('absence_cancel',{'csrf':a,'id':aid});self.assertEqual(len(self.call('data',client='carolina')['plan']),len(original))
        self.assertEqual(len(self.call('data',client='carolina')['audit']),1)
        self.assertEqual([e['event'] for e in self.call('management')['events'][:3]],['CANCELAR_AUSENCIA','EDITAR_AUSENCIA','CREAR_AUSENCIA'])
        future=(day+timedelta(days=1)).isoformat();self.call('absence_save',{**payload,'start':future});self.assertEqual(len(self.call('data',client='carolina')['plan']),len(original))
        with patch.object(s,'today',return_value=future):self.assertEqual(self.call('data',client='carolina')['plan'],[])
        s.initialize();self.assertEqual(len(self.call('management')['absences']),2)
if __name__=='__main__':unittest.main()
