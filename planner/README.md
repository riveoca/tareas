# Cargar tareas en Microsoft Planner

Crea y actualiza tareas de un plan de Planner manejando la página web con Playwright. No hace falta
API ni permisos de Microsoft Graph: usa tu sesión de Chrome.

## Archivos

| Archivo | Para qué |
| --- | --- |
| `instalar.sh` | Crea `planner/.venv` con Playwright (una sola vez). |
| `abrir_chrome.sh` | Abre una ventana de Chrome aparte (perfil en `planner/chrome-perfil/`) lista para ser controlada. |
| `planner.py` | Comandos `ver`, `aplicar`, `borrar` y `asignar`. |
| `ejemplo_tareas.json` | Ejemplo de entrada: las 33 tareas del plan Trazabilidad. |
| `validacion_tareas.json` | Ejemplo de entrada: tareas de validación del plan Trazabilidad, con responsable. |

## Procedimiento

1. Instalar (solo la primera vez):
   ```bash
   ./planner/instalar.sh
   ```
2. Abrir Chrome e iniciar sesión en Planner con la cuenta de la empresa en esa ventana:
   ```bash
   ./planner/abrir_chrome.sh
   ```
3. Revisar el plan (solo lectura):
   ```bash
   planner/.venv/bin/python planner/planner.py ver --plan "Trazabilidad"
   ```
4. Preparar un JSON con las tareas (ver formato abajo) y simular:
   ```bash
   planner/.venv/bin/python planner/planner.py aplicar --plan "Trazabilidad" mis_tareas.json --simular
   ```
5. Aplicar:
   ```bash
   planner/.venv/bin/python planner/planner.py aplicar --plan "Trazabilidad" mis_tareas.json
   ```
6. Borrar una tarea por su título exacto:
   ```bash
   planner/.venv/bin/python planner/planner.py borrar --plan "Trazabilidad" "Título de la tarea"
   ```
7. Poner un responsable en todas las tareas del plan (incluidas las completadas); el nombre es el que
   aparece en el selector «Asignar a» de Planner:
   ```bash
   planner/.venv/bin/python planner/planner.py asignar --plan "Trazabilidad" "Nombre Apellido"
   ```

## Formato del JSON

Lista de tareas en el orden en que deben verse (de arriba abajo en cada depósito):

```json
[
  {
    "titulo": "Configuración base del proyecto",
    "deposito": "Ejecución",
    "inicio": "04/09/2026",
    "fin": "04/09/2026",
    "descripcion": "Primera línea.\nSegunda línea.",
    "estado": "Completado",
    "responsable": "Nombre Apellido"
  }
]
```

- `titulo` es obligatorio y es la clave: si ya existe una tarea con ese título exacto no se crea otra,
  solo se completan sus campos.
- `deposito` debe ser el nombre exacto de una columna del plan (el script lo valida antes de empezar).
- Fechas en formato `dd/mm/aaaa`. `fin` es opcional (tareas continuas).
- `estado`: `No iniciado`, `En curso` o `Completado`.
- `responsable` (opcional): nombre tal como aparece en el selector «Asignar a»; se añade si aún no está.
- Las fechas y la descripción solo se escriben si están vacías en Planner; el depósito y el estado
  se cambian siempre al valor del JSON.

## Notas

- Planner solo dibuja las tarjetas visibles y pliega las completadas; el script recorre cada columna
  con la rueda del ratón y despliega «Tareas completadas» para encontrarlas.
- Depende de los textos de la interfaz en español («Agregar tarea», «Fecha de inicio», «Depósito»…).
  Si Microsoft cambia la interfaz, hay que ajustar esos textos en `planner.py`.
- En Claude Code con modo automático, cada paso del navegador puede pedir permiso. Para evitarlo,
  añadir en `/permissions` (Allow) la regla `Bash(planner/.venv/bin/python:*)`.
- `planner/chrome-perfil/` guarda la sesión de esa ventana de Chrome y está en `.gitignore`.
