# CAT | Planificación Operativa — v2.0

## Novedades: roles, vacaciones y suplencias

- **Administrador (`admin`)**: ve todas las campañas, configura accesos y registra ausencias, asignaciones y auditoría administrativa. Es una cuenta separada de las cinco jefaturas. Activación con clave de un solo uso generada al iniciar, sin contraseña predeterminada.
- **Jefe**: ve y edita sus servicios titulares y las campañas para las que posee cobertura activa. Los dos roles son fijos; no se habilita la promoción de jefes a administrador desde la interfaz. La titularidad original se mantiene según el archivo de semilla.
- **Vacaciones, licencia u otra ausencia**: ingresar como administrador, ir a «Vacaciones y cobertura», seleccionar titular, fecha de inicio y fin (inclusive) y suplente para cada campaña. Se pueden repartir campañas o asignarlas en bloque a un mismo jefe. Solo son elegibles cuentas activadas que no tengan ausencias superpuestas. Se permiten campañas sin cobertura, accesibles únicamente por admin durante la ausencia, previa advertencia en la interfaz.
- La ausencia bloquea los permisos del titular durante el período. El suplente puede editar las fechas del mes de planificación independientemente de la fecha de cobertura. Al finalizar o cancelar la ausencia, el titular recupera acceso y el suplente lo pierde. No se mueve ni duplica la planificación.
- Los permisos se recalculan en el servidor en cada consulta y guardado, usando la fecha de Buenos Aires (UTC−3). Si el usuario tiene una pantalla previamente cargada, deberá pulsar «Actualizar datos» para reflejar la nueva lista; un guardado fuera del permiso vigente será rechazado.
- El administrador puede editar o cancelar ausencias vigentes/futuras. Se rechazan solapamientos y ausencias de suplentes comprometidos hasta que se reasigne su cobertura. Las ausencias finalizadas se conservan. La auditoría administrativa registra cambios de accesos y anteriores/nuevas asignaciones. El historial operativo mantiene titular y editor real incluso tras el regreso.

### Actualizar desde v1.0 sin perder información

Detener el servidor y realizar una copia de seguridad de la base existente (`python tools/backup.py` desde la carpeta anterior). Abrir el proyecto v2.0 y copiar la carpeta `data` anterior completa con el servicio detenido, o configurar `CAT_DATA_DIR` apuntando al directorio persistente anterior. No reemplazar la base por una nueva ni combinar archivos de bases distintas. Al arrancar, `initialize()` crea las tablas adicionales sin borrar usuarios, planificación ni historial. Los usuarios existentes conservan sus claves. Guardar una copia anterior para volver atrás si fuera necesario. Las nuevas funciones solo están disponibles en v2.0.



Proyecto editable para VS Code. Frontend HTML/CSS/JS, backend Python WSGI y SQLite. No usa IA, servicios externos ni una base de datos corporativa. Diciembre 2026: 5 jefaturas, 59 combinaciones jefatura/campaña, 1.829 registros diarios. La semilla se recuperó del PHP preparado previamente a partir de los cinco Excel; no se recalculó el Excel en esta entrega.

## Ejecutar localmente (Windows)

1. Descomprimir y abrir la carpeta `CAT_Planificacion` en VS Code.
2. Verificar Python 3.10+ con `py --version` (o `python --version`).
3. En la terminal integrada instalar las dependencias con `py -m pip install -r requirements.txt` y ejecutar `py server.py` (o usar `python`).
4. Abrir http://127.0.0.1:8000. La terminal muestra una clave inicial aleatoria, de un solo uso. Copiarla en la pantalla de activación y crear una contraseña de administrador de 12 caracteres como mínimo.
5. Ingresar como `admin`. En Administrar accesos crear la contraseña de cada jefe (Carolina, Ismael, Mariela, Roxana, Salvador). Entregarla por canal seguro. Probar los permisos en una ventana privada.
6. Elegir campaña y editar una fecha o aplicar un rango. Pulsar Guardar cambios. Verificar el historial. Al cerrar y volver a abrir, la información queda en `data/planificacion.sqlite`.

Si se usa la extensión Python de VS Code, F5 también inicia el servidor. `iniciar.bat` es una comodidad local opcional. No se distribuye a los jefes.

## Criterios funcionales

- La línea base permanece fija. Amarillo = diferencia actual contra base; borde azul = borrador pendiente. El historial se conserva incluso si se vuelve al original.
- Horas objetivo = dotación × jornada, por día. No se aplica ausentismo ni se valorizan pesos sin valores hora confirmados.
- Las modificaciones por rango se agrupan bajo un ID de operación y conservan detalle por día. El selector permite limitar a días originalmente activos o incluir todo el rango. El tipo de día es el de la semilla.
- El historial guarda UTC y la interfaz muestra hora de Buenos Aires. El CSV conserva la marca ISO original. El filtro de fechas del historial utiliza la fecha de planificación afectada.
- Solo el administrador ve todo; un jefe puede leer/editar sus campañas titulares cuando está disponible y las suplencias activas que le asignen. La API aplica permisos, no solo la interfaz. Las revisiones evitan sobrescribir datos desactualizados. Guardar es transaccional: si falla un registro, se revierte la operación completa.
- El historial se descarga como CSV separado por punto y coma y con BOM UTF-8. La planificación se descarga como XLSX. El historial es acumulativo de cambios guardados; no captura borradores descartados ni cada pulsación de teclado.
- La semilla corresponde a diciembre 2026. El administrador crea el mes siguiente copiando, para cada día, el último día equivalente de la semana del mes anterior y lo habilita para los jefes. Puede habilitar un mes ya existente y consultar los anteriores; los jefes solo acceden al mes habilitado. En Feriados puede marcar fechas nacionales sugeridas y agregar fechas adicionales, antes o después de crear el mes. Marcar o quitar un feriado cambia el tipo de día en toda la planificación, pero no modifica dotación ni jornadas; el resumen utiliza esas fechas para determinar el primer día hábil. El listado local no se actualiza automáticamente: 2027 incluye únicamente inamovibles y los años posteriores deben verificarse en fuentes oficiales. La descarga XLSX incluye todas las campañas autorizadas del mes seleccionado, independientemente de los filtros de la pantalla, y requiere guardar los cambios pendientes. Valores hora y SSO no implementados.
- El administrador puede indicar un cliente independiente al crear una campaña y corregir el cliente de las campañas existentes desde Campañas. El cliente se conserva al renombrar la campaña o el responsable y se utiliza en los filtros, el resumen y los archivos Excel.
- En Personal, el administrador puede pegar una matriz mensual o cargar un archivo XLSX/TSV/CSV con una campaña por fila y todos los días del mes como columnas. También admite el formato PLP con bloques separados de dotaciones y horas, responsable, cliente y site: toma las horas del segundo bloque y verifica que coincidan con la dotación del primero. La previa muestra personas como horas / 6 sin redondeo y señala diferencias con los totales informados. Las campañas sin datos completos quedan pendientes, no se convierten a cero ni se incorporan. Las previas se guardan por versión y no alteran por sí mismas la planificación. Para incorporarlas, el mes debe existir y deben revisarse todos los responsables. Si se crean accesos sugeridos, su usuario y clave inicial son el nombre completo, con cambio obligatorio de clave al ingresar. La incorporación conserva la base original de registros existentes, registra los cambios y solo afecta al mes seleccionado; no se propaga a meses posteriores. Las filas de totales no se importan como campañas.

## Estructura

`server.py` API y base de datos; `web/` interfaz; `seed/` datos de arranque; `tests/` pruebas; `tools/backup.py` respaldo consistente. `production.py` entrada WSGI. La base y la clave se generan fuera de `web/`, y el servidor solo publica tres recursos explícitos.

## Entrega a Sistemas

El servidor de desarrollo es para pruebas locales, no para producción. Si existe Python y un servicio WSGI compatible, Sistemas puede desplegar la carpeta, usar `production:application` y configurar HTTPS y acceso de red interno. Ejemplo con Waitress (si está autorizado y no existe otro WSGI):

```
python -m pip install -r requirements.txt
waitress-serve --listen=127.0.0.1:8000 production:application
```

Variables de entorno: `CAT_DATA_DIR` (ruta privada persistente y con permisos de escritura), `CAT_SECURE_COOKIE=1` detrás de HTTPS, `CAT_HOST` y `CAT_PORT` para desarrollo. Configurar proxy HTTPS, ejecución como servicio, protección de red y límites de peticiones/intentos de login. No exponer `data/`, ni la clave de activación, ni el ZIP. SQLite debe residir en disco local persistente del servidor, no en una unidad de red compartida; una sola instancia de aplicación es el despliegue inicial recomendado. Los jefes solo reciben URL y credenciales. Si el servidor admite únicamente PHP, consultar antes de migrar: el proyecto Python no se ejecuta como un HTML estático.

Las contraseñas usan PBKDF2-SHA256 con sal aleatoria, las sesiones caducan a las 12 horas, los cambios usan CSRF y el historial tiene triggers que impiden UPDATE/DELETE ordinarios. Esto no equivale a auditoría inviolable frente a un administrador de base de datos. Revisar seguridad, política de contraseñas, respaldos, recuperación, permisos del sistema y accesibilidad antes de producción. No se incluye SSO ni bloqueo avanzado por intentos.

## Respaldo y pruebas

`python tools/backup.py` crea una copia consistente en `backups/`; protegerla como dato interno. Para restaurar, detener el servicio, conservar una copia de seguridad de la base actual y archivos WAL/SHM, reemplazar por una copia verificada y reiniciar. No borrar la base: se perdería el historial y se volvería a la semilla.

`python -m unittest discover -s tests -v` prueba activación, autenticación, datos iniciales, aislamiento de jefaturas, guardado diario y mensual, reversión, conflicto de versiones, persistencia tras reinicialización, rollback, CSRF y protección de historial. `node --check web/app.js` valida sintaxis JavaScript si Node está disponible. En v2.0 se prueba además programación futura, división de cobertura, acceso por campaña, rechazo a cambios ajenos y del titular ausente, autoría de la suplencia, conflictos por ausencias superpuestas, reasignación, vencimiento automático simulado, cancelación y persistencia de las ausencias. No se realizaron pruebas visuales de navegador ni despliegue corporativo en esta entrega.
