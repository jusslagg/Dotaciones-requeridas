import unittest
from io import BytesIO
from openpyxl import load_workbook
from site_report import report, workbook, filter_report


class FakeDB:
    def execute(self, query, params=()):
        if 'FROM holidays' in query:
            return [('2026-12-08',), ('2026-12-25',)] if params[0] == '2026-12' else []
        if 'WHERE month=' in query:
            class Cursor:
                def fetchone(self):
                    return (params[0],) if params[0] == '2026-12' else None
            return Cursor()
        return [('2026-12',)]


class SiteReportTests(unittest.TestCase):
    def test_historical_personal_groups_are_combined_in_front(self):
        result = report(FakeDB(), '2026-11', None, {})
        personal = [r for r in result['changes'] if r['campaign'] == 'PERSONAL']
        self.assertEqual(len(personal), 1)
        self.assertAlmostEqual(personal[0]['required'], 1003.3859649122805)
        self.assertAlmostEqual(personal[0]['previous'], 954.68)
        self.assertAlmostEqual(personal[0]['delta'], 48.7059649122805)
        self.assertTrue(any(r['campaign'] == 'Personal CAT' for r in result['current']['rows']))
        front = load_workbook(BytesIO(workbook(result)), data_only=True)['Front']
        rows = [r for r in front.iter_rows(min_row=3, values_only=True) if r[0] == 'PERSONAL']
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0][3], personal[0]['delta'])

    def test_historical_total_compares_with_all_live_responsibles(self):
        def summarize(db, month):
            return {'rows': [
                {'jefe':'A','client':'PERSONAL','campaign':'ABONOS','required':10,'hours':100},
                {'jefe':'B','client':'PERSONAL','campaign':'SMB','required':20,'hours':200},
                {'jefe':'B','client':'OTRO','campaign':'OTRO','required':5,'hours':50},
            ]}
        result = report(FakeDB(), '2026-12', summarize, {})
        personal = [r for r in result['changes'] if r['campaign'] == 'PERSONAL']
        self.assertEqual(len(personal), 1)
        self.assertAlmostEqual(personal[0]['required'], 300 / (21 * 6))
        self.assertAlmostEqual(personal[0]['previous'], 1003.3859649122805)

    def test_filters_keep_summary_and_front_independent_in_excel(self):
        original = report(FakeDB(), '2026-11', None, {})
        filtered = filter_report(original, ['Salvador Almeira'], ['Metrogas'], ['PERSONAL'])
        self.assertEqual(len(filtered['current']['rows']), 1)
        self.assertEqual(filtered['current']['total_required'], 45)
        self.assertEqual(filtered['current']['total_hours'], 5670)
        self.assertEqual([r['campaign'] for r in filtered['changes']], ['PERSONAL'])
        book = load_workbook(BytesIO(workbook(filtered)), data_only=True)
        self.assertEqual(book['Resumen site']['B3'].value, 'Metrogas')
        self.assertEqual(book['Resumen site']['A4'].value, 'Total filtrado')
        self.assertEqual(book['Resumen site']['C4'].value, 45)
        self.assertEqual(book['Front']['A3'].value, 'PERSONAL')
        self.assertGreater(len(original['current']['rows']), 1)

    def test_front_groups_clients_across_services_and_historical_names(self):
        def summarize(db, month):
            return {'rows': [
                {'jefe':'A','client':'SANTANDER','campaign':'GETNET','required':20,'hours':200},
                {'jefe':'B','client':'SANTANDER','campaign':'OTRA','required':50,'hours':500},
                {'jefe':'A','client':'BBVA OPENPAY','campaign':'RRSS','required':3,'hours':100},
                {'jefe':'B','client':'BBVA OPENPAY','campaign':'CUSTOMER','required':6,'hours':200},
            ]}
        result = report(FakeDB(), '2026-12', summarize, {})
        santander = [r for r in result['changes'] if r['campaign'] == 'SANTANDER']
        self.assertEqual(len(santander), 1)
        self.assertEqual(santander[0]['required'], 70)
        self.assertEqual(santander[0]['previous'], 542)
        openpay = next(r for r in result['changes'] if r['campaign'] == 'BBVA OPENPAY')
        self.assertEqual((openpay['required'],openpay['previous']), (9,12))
        self.assertFalse(any(r['campaign'] in ('Getnet Argentina','Openpay') for r in result['changes']))
        self.assertEqual(load_workbook(BytesIO(workbook(result)))['Front']['A2'].value,'Cliente')

    def test_bsf_compares_against_historical_carrefour(self):
        def summarize(db, month):
            return {'rows':[{'jefe':'Carolina','client':'BSF','campaign':'BSF','required':7,'hours':882}]}
        unchanged=report(FakeDB(),'2026-12',summarize,{})
        self.assertFalse(any(r['campaign'] in ('BSF','Carrefour') for r in unchanged['changes']))
        def increased(db, month):
            return {'rows':[{'jefe':'Carolina','client':'BSF','campaign':'BSF','required':8,'hours':882}]}
        change=next(r for r in report(FakeDB(),'2026-12',increased,{})['changes'] if r['campaign']=='BSF')
        self.assertEqual((change['previous'],change['required'],change['delta']),(7,8,1))


if __name__ == '__main__':
    unittest.main()
