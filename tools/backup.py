import sys,sqlite3,datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import DATA, ROOT
src=DATA/'planificacion.sqlite'
if not src.is_file():raise SystemExit('No existe la base de datos')
out=ROOT/'backups';out.mkdir(exist_ok=True)
path=out/('planificacion_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'.sqlite')
with sqlite3.connect(src) as a,sqlite3.connect(path) as b:a.backup(b)
print(path)
