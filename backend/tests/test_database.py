from datetime import date
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
import weakref

from backend.app.csv_parser import parse_money, parse_row, ParseResult
from backend.app.database import ReceivablesDatabase
from backend.app.validation import validar_base
from backend.tests.test_validator import FUNDO, titulo


class DatabaseTests(unittest.TestCase):
    def test_money_rejects_subcent_and_overflow_but_accepts_trailing_zeros(self):
        for value in ('100,005', '0,0000000000000000000000000001', '92233720368547758,08', '1e1000'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_money(value)
        for value in ('100,0000', '0,00', '92233720368547758,07'):
            self.assertTrue(parse_money(value).is_finite())

    def test_all_rows_are_kept_and_duplicates_are_global(self):
        rows=[titulo(NU_DOCUMENTO='0001'), titulo(NU_DOCUMENTO='1'), titulo(NU_DOCUMENTO='0001'),
              titulo(NU_DOCUMENTO='0001',VALOR_NOMINAL='invalid'),titulo(NU_DOCUMENTO='')]
        with ReceivablesDatabase(':memory:') as db:
            db.import_rows((parse_row((i+2,r)) for i,r in enumerate(rows)), FUNDO, chunk_size=1)
            result=db.connection.execute('SELECT linha,documento,duplicado_de,erros FROM recebiveis ORDER BY linha').fetchall()
            self.assertEqual(len(result),5)
            self.assertEqual(result[2]['duplicado_de'],2)
            self.assertIsNone(result[1]['duplicado_de'])
            self.assertIsNotNone(result[3]['erros'])
            self.assertEqual([r['documento'] for r in result],['0001','1','0001','0001',''])

    def test_import_retains_no_row_objects_and_uses_transactions(self):
        class RowData(dict):
            pass
        references=[]
        raw=titulo()
        parsed=parse_row((2,raw)).data
        def rows():
            for i in range(100):
                data=RowData({**parsed,'NU_DOCUMENTO':str(i)})
                references.append(weakref.ref(data))
                yield ParseResult(i+2,data,[],str(i))
                self.assertLessEqual(sum(ref() is not None for ref in references),2)
        with ReceivablesDatabase(':memory:') as db:
            trace=[]
            db.connection.set_trace_callback(trace.append)
            db.import_rows(rows(),FUNDO,chunk_size=2)
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM recebiveis').fetchone()[0],100)
            self.assertTrue(all(ref() is None for ref in references))
            self.assertEqual(sum(s=='BEGIN ' or s=='BEGIN' for s in trace),1)

    def test_failed_import_rolls_back_and_connection_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'base.sqlite'
            db=ReceivablesDatabase(path)
            def rows():
                yield parse_row((2,titulo()))
                raise ValueError('broken CSV')
            with db, self.assertRaisesRegex(ValueError,'broken CSV'):
                db.import_rows(rows(),FUNDO,chunk_size=1)
            with self.assertRaises(sqlite3.ProgrammingError):
                db.connection.execute('SELECT 1')
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM recebiveis').fetchone()[0],0)

    def test_separate_databases_are_isolated(self):
        config={'fundo':FUNDO,'validadores':[]}
        with ReceivablesDatabase(':memory:') as first, ReceivablesDatabase(':memory:') as second:
            first.import_rows([parse_row((2,titulo()))],FUNDO)
            second.import_rows([parse_row((2,titulo(NU_DOCUMENTO='2')))],FUNDO)
            validar_base(first,config,data_referencia=date(2026,10,24))
            validar_base(second,config,data_referencia=date(2026,10,24))
            self.assertEqual(next(first.iter_records())['id'],'0001')
            self.assertEqual(next(second.iter_records())['id'],'2')
