"""Lee y carga tareas en un plan de Microsoft Planner manejando la web con Playwright.

Se conecta a un Chrome abierto con `./abrir_chrome.sh` (puerto de depuración 9333) donde el usuario ya
inició sesión en Planner. No usa la API de Microsoft Graph.

Uso:
    python planner.py ver      --plan "Trazabilidad"
    python planner.py aplicar  --plan "Trazabilidad" tareas.json [--simular]
    python planner.py borrar   --plan "Trazabilidad" "Título exacto de la tarea"
    python planner.py asignar  --plan "Trazabilidad" "Nombre del responsable" [--simular]
"""
import argparse
import json
import sys

from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9333"
DLG = "Cuadro de diálogo de detalles de la tarea"
NOTAS_VACIAS = ("", "Escriba una descripción o agregue notas aquí")


def conectar(p):
    b = p.chromium.connect_over_cdp(CDP)
    paginas = [x for c in b.contexts for x in c.pages if "planner" in x.url]
    if not paginas:
        sys.exit("No hay ninguna pestaña de Planner abierta. Ejecuta ./abrir_chrome.sh e inicia sesión.")
    pg = paginas[0]
    pg.set_viewport_size({"width": 1600, "height": 1000})
    return pg


def cerrar_panel(pg):
    for _ in range(3):
        if not pg.get_by_role("dialog", name=DLG).count():
            return
        pg.get_by_role("dialog", name=DLG).get_by_role("button", name="Cerrar").click()
        pg.wait_for_timeout(1500)


def abrir_plan(pg, plan):
    cerrar_panel(pg)
    if pg.get_by_role("heading", name=plan, exact=True).count() or (
            "/plan/" in pg.url and pg.get_by_text(plan, exact=True).count()):
        return
    pg.get_by_text("Mis planes", exact=True).first.click()
    pg.wait_for_timeout(4000)
    pg.get_by_text(plan, exact=True).first.click()
    pg.wait_for_timeout(6000)
    if "/plan/" not in pg.url:
        sys.exit(f"No pude abrir el plan «{plan}». Revisa el nombre exacto en «Mis planes».")


def depositos(pg):
    """Nombres de los depósitos (columnas) del tablero, en orden."""
    textos = pg.locator("body").inner_text().split("\n")
    nombres = []
    for i, t in enumerate(textos[:-1]):
        if textos[i + 1].strip() == "Agregar tarea" and t.strip() and t.strip() != "Agregar tarea":
            nombres.append(t.strip())
    return nombres


def desplegar_completadas(pg):
    """Planner pliega las tareas completadas; las despliega para poder encontrarlas."""
    for b in pg.get_by_role("button").filter(has_text="Tareas completadas").all():
        if b.get_attribute("aria-expanded") == "false":
            b.click()
            pg.wait_for_timeout(800)


def recorrer(pg, al_ver):
    """Recorre cada columna con la rueda del ratón (Planner solo dibuja las tarjetas visibles)."""
    for x in (180, 500, 820, 1140, 1460):
        pg.mouse.move(x, 600)
        for _ in range(20):
            pg.mouse.wheel(0, -800)
        pg.wait_for_timeout(400)
        for _ in range(30):
            desplegar_completadas(pg)
            if al_ver():
                return True
            pg.mouse.wheel(0, 450)
            pg.wait_for_timeout(450)
    return False


def buscar(pg, titulo):
    loc = pg.get_by_text(titulo, exact=True)
    return loc if recorrer(pg, lambda: loc.count() > 0) else None


def elegir(d, pg, etiqueta, valor):
    combo = d.get_by_label(etiqueta).first
    if combo.inner_text().strip() == valor:
        return False
    opcion = pg.get_by_role("option", name=valor, exact=True)
    # Justo después de escribir las notas Planner a veces ignora el primer clic en el desplegable.
    for _ in range(4):
        combo.click()
        pg.wait_for_timeout(1200)
        if opcion.count():
            break
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(1500)
    opcion.click()
    pg.wait_for_timeout(1500)
    return True


def asignar(d, pg, nombre):
    """Añade a `nombre` como responsable si aún no lo es. Devuelve True si cambió algo."""
    boton = d.get_by_role("button", name="asignar usuarios a esta tarea").first
    if nombre.lower() in (boton.get_attribute("aria-label") or "").lower():
        return False
    boton.click()
    pg.wait_for_timeout(1200)
    pg.keyboard.type(nombre)
    pg.wait_for_timeout(2500)
    pg.get_by_role("option").filter(has_text=nombre).first.click()
    pg.wait_for_timeout(1500)
    # Mientras el selector de personas está abierto, el panel pierde su nombre accesible.
    for _ in range(3):
        if not pg.get_by_role("option").count():
            break
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(1200)
    if nombre.lower() not in (d.get_by_role("button", name="asignar usuarios a esta tarea").first
                              .get_attribute("aria-label", timeout=5000) or "").lower():
        sys.exit(f"No pude confirmar la asignación de «{nombre}»; reviso a mano antes de seguir.")
    return True


def titulos(pg):
    """Títulos de todas las tarjetas del plan, incluidas las completadas."""
    vistas = {}

    def anotar():
        for c in pg.locator("[data-testid=task-card-title]").all():
            t = c.inner_text().strip()
            if t:
                vistas[t] = vistas.get(t, 0) or 1
        return False

    recorrer(pg, anotar)
    return list(vistas)


def cmd_ver(pg, args):
    abrir_plan(pg, args.plan)
    print("Depósitos:", ", ".join(depositos(pg)))
    vistas = titulos(pg)
    print(f"{len(vistas)} tareas:")
    for t in vistas:
        print(" -", t)


def cmd_asignar(pg, args):
    abrir_plan(pg, args.plan)
    todas = titulos(pg)
    print(f"{len(todas)} tareas en el plan.")
    for titulo in todas:
        loc = buscar(pg, titulo)
        if loc is None or loc.count() != 1:
            print("OMITIDA, no la encontré una sola vez:", titulo)
            continue
        if args.simular:
            print("REVISARÍA:", titulo)
            continue
        loc.click()
        pg.wait_for_timeout(2500)
        d = pg.get_by_role("dialog", name=DLG)
        print("ASIGNADA |" if asignar(d, pg, args.nombre) else "YA ESTABA |", titulo)
        cerrar_panel(pg)


def cmd_aplicar(pg, args):
    tareas = json.load(open(args.archivo, encoding="utf-8"))
    abrir_plan(pg, args.plan)
    validos = depositos(pg)
    malos = {t["deposito"] for t in tareas if t.get("deposito") and t["deposito"] not in validos}
    if malos:
        sys.exit(f"Depósitos que no existen en el plan: {malos}. Válidos: {validos}")
    # Planner agrega cada tarea nueva arriba del depósito: se recorren al revés para que queden en orden.
    for t in reversed(tareas):
        titulo = t["titulo"]
        loc = buscar(pg, titulo)
        if loc is not None and loc.count() > 1:
            print("OMITIDA, aparece", loc.count(), "veces:", titulo)
            continue
        if loc is None:
            if args.simular:
                print("CREARÍA:", titulo)
                continue
            pg.mouse.move(180, 600)
            for _ in range(20):
                pg.mouse.wheel(0, -800)
            pg.get_by_text("Agregar tarea", exact=True).first.click()
            pg.wait_for_timeout(1200)
            pg.keyboard.type(titulo)
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(2500)
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(1500)
            loc = pg.get_by_text(titulo, exact=True)
            if loc.count() != 1:
                sys.exit(f"No pude confirmar la creación de «{titulo}»; reviso a mano antes de seguir.")
        elif args.simular:
            print("YA EXISTE (se completarían campos vacíos, depósito y estado):", titulo)
            continue
        loc.click()
        pg.wait_for_timeout(2500)
        d = pg.get_by_role("dialog", name=DLG)
        for etiqueta, clave in (("Fecha de inicio", "inicio"), ("Fecha de vencimiento", "fin")):
            campo = d.get_by_label(etiqueta, exact=True)
            if t.get(clave) and not campo.input_value():
                campo.fill(t[clave])
                campo.press("Tab")
                pg.wait_for_timeout(1200)
        notas = d.locator("[contenteditable=true]").first
        if t.get("descripcion") and notas.inner_text().strip() in NOTAS_VACIAS:
            notas.click()
            pg.wait_for_timeout(500)
            for i, linea in enumerate(t["descripcion"].split("\n")):
                if i:
                    pg.keyboard.press("Shift+Enter")
                pg.keyboard.type(linea)
            pg.wait_for_timeout(1500)
        if t.get("deposito"):
            elegir(d, pg, "Depósito", t["deposito"])
        if t.get("estado"):
            elegir(d, pg, "Estado", t["estado"])
        if t.get("responsable"):
            asignar(d, pg, t["responsable"])
        print("OK |", d.get_by_label("Depósito").first.inner_text(), "|",
              d.get_by_label("Estado").first.inner_text(), "|",
              d.get_by_label("Fecha de inicio", exact=True).input_value(), "–",
              d.get_by_label("Fecha de vencimiento", exact=True).input_value(), "|", titulo)
        cerrar_panel(pg)


def cmd_borrar(pg, args):
    abrir_plan(pg, args.plan)
    loc = buscar(pg, args.titulo)
    if loc is None or loc.count() != 1:
        sys.exit(f"No encontré exactamente una tarea «{args.titulo}».")
    loc.click()
    pg.wait_for_timeout(2500)
    d = pg.get_by_role("dialog", name=DLG)
    d.get_by_role("button", name="Más opciones").click()
    pg.wait_for_timeout(1000)
    pg.get_by_role("menuitem", name="Eliminar").click()
    pg.wait_for_timeout(1500)
    print("Eliminada:", args.titulo, "(Planner muestra unos segundos un aviso con «Deshacer»)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for nombre in ("ver", "aplicar", "borrar", "asignar"):
        s = sub.add_parser(nombre)
        s.add_argument("--plan", required=True, help="Nombre exacto del plan en «Mis planes»")
        if nombre == "aplicar":
            s.add_argument("archivo", help="JSON con la lista de tareas (ver ejemplo_tareas.json)")
            s.add_argument("--simular", action="store_true", help="Solo muestra qué haría, sin cambiar nada")
        if nombre == "borrar":
            s.add_argument("titulo")
        if nombre == "asignar":
            s.add_argument("nombre", help="Nombre tal como aparece en el selector de Planner")
            s.add_argument("--simular", action="store_true", help="Solo lista las tareas, sin cambiar nada")
    args = ap.parse_args()
    with sync_playwright() as p:
        pg = conectar(p)
        {"ver": cmd_ver, "aplicar": cmd_aplicar, "borrar": cmd_borrar, "asignar": cmd_asignar}[args.cmd](pg, args)


if __name__ == "__main__":
    main()
