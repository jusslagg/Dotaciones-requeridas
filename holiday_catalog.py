"""Feriados nacionales de Argentina verificados, sin días no laborables turísticos.

2026: calendario del BCRA (Com. C 101352), Ley 27.399 y Decreto 1103/2026.
2027: solo feriados nacionales inamovibles de la Ley 27.399, con Carnaval y
Viernes Santo en sus fechas de 2027. Los trasladables se dejan sin anticipar.
"""
SOURCES=[
    ('Calendario del BCRA 2026','https://www.bcra.gob.ar/archivos/Pdfs/comytexord/C101352.pdf'),
    ('Ley 27.399','https://www.argentina.gob.ar/normativa/nacional/ley-27399-281835/texto'),
    ('Calendario oficial de feriados','https://www.argentina.gob.ar/feriados'),
]
CATALOG={
2026:[
('01-01','Año Nuevo'),('02-16','Carnaval'),('02-17','Carnaval'),
('03-24','Día Nacional de la Memoria por la Verdad y la Justicia'),
('04-02','Día del Veterano y de los Caídos en la Guerra de Malvinas'),
('04-03','Viernes Santo'),('05-01','Día del Trabajador'),('05-25','Día de la Revolución de Mayo'),
('06-15','Paso a la Inmortalidad del General Martín Miguel de Güemes'),
('06-20','Paso a la Inmortalidad del General Manuel Belgrano'),
('07-09','Día de la Independencia'),('08-17','Paso a la Inmortalidad del General José de San Martín'),
('10-12','Día del Respeto a la Diversidad Cultural'),('11-09','Feriado nacional extraordinario'),
('11-23','Día de la Soberanía Nacional'),('12-08','Inmaculada Concepción de María'),('12-25','Navidad')],
2027:[
('01-01','Año Nuevo'),('02-08','Carnaval'),('02-09','Carnaval'),
('03-24','Día Nacional de la Memoria por la Verdad y la Justicia'),('03-26','Viernes Santo'),
('04-02','Día del Veterano y de los Caídos en la Guerra de Malvinas'),('05-01','Día del Trabajador'),
('05-25','Día de la Revolución de Mayo'),('06-20','Paso a la Inmortalidad del General Manuel Belgrano'),
('07-09','Día de la Independencia'),('12-08','Inmaculada Concepción de María'),('12-25','Navidad')],
}

def official_holidays(year):
    return [{'day':f'{year}-{day}','name':name} for day,name in CATALOG.get(year,[])]

def official_non_working_days(year):
    """Verified national holidays plus fixed dates valid in every year."""
    fixed=('01-01','03-24','04-02','05-01','05-25','06-20','07-09','12-08','12-25')
    return {f'{year}-{day}' for day in fixed} | {entry['day'] for entry in official_holidays(year)}
