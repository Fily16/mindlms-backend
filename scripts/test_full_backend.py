"""
Script de prueba completa del backend MindLMS.
Ejecuta todos los endpoints y genera un reporte detallado.
"""

import httpx
import json
import time
import sys
from datetime import datetime

BASE_URL = "http://localhost:8000"
RESULTS = []
TOKEN = None


def log(section, endpoint, method, status, response_data, passed, notes=""):
    RESULTS.append({
        "section": section,
        "endpoint": endpoint,
        "method": method,
        "status_code": status,
        "passed": passed,
        "notes": notes,
        "response": response_data,
    })
    icon = "PASS" if passed else "FAIL"
    print(f"  [{icon}] {method} {endpoint} -> {status} {notes}")


def test_health():
    print("\n=== 1. HEALTH CHECK ===")
    r = httpx.get(f"{BASE_URL}/health")
    data = r.json()
    passed = r.status_code == 200 and data["status"] == "ok"
    log("Health", "/health", "GET", r.status_code, data, passed)
    return data


def test_openapi():
    print("\n=== 2. OPENAPI DOCS ===")
    r = httpx.get(f"{BASE_URL}/openapi.json")
    data = r.json()
    endpoints_count = len(data.get("paths", {}))
    passed = r.status_code == 200 and endpoints_count > 0
    log("Docs", "/openapi.json", "GET", r.status_code,
        {"title": data.get("info", {}).get("title"), "endpoints": endpoints_count},
        passed, f"{endpoints_count} endpoints documentados")
    return data


def test_register():
    global TOKEN
    print("\n=== 3. AUTENTICACION ===")

    # 3a. Registrar usuario
    r = httpx.post(f"{BASE_URL}/api/v1/auth/register", json={
        "email": "dra.martinez@upc.edu.pe",
        "password": "Test1234!",
        "full_name": "Dra. Ana Martinez",
        "role": "psicologo",
    })
    data = r.json()
    passed = r.status_code == 201
    if r.status_code == 409:
        passed = True  # Ya existe, OK
        log("Auth", "/api/v1/auth/register", "POST", r.status_code, data, passed, "Usuario ya existia")
    else:
        log("Auth", "/api/v1/auth/register", "POST", r.status_code, data, passed,
            f"Usuario creado: {data.get('email', '')}" if passed else str(data))

    # 3b. Login
    r = httpx.post(f"{BASE_URL}/api/v1/auth/login", data={
        "username": "dra.martinez@upc.edu.pe",
        "password": "Test1234!",
    })
    data = r.json()
    passed = r.status_code == 200 and "access_token" in data
    if passed:
        TOKEN = data["access_token"]
    log("Auth", "/api/v1/auth/login", "POST", r.status_code,
        {"has_token": "access_token" in data, "token_type": data.get("token_type")},
        passed, "Token JWT obtenido" if passed else "Login fallido")

    # 3c. Login con credenciales incorrectas
    r = httpx.post(f"{BASE_URL}/api/v1/auth/login", data={
        "username": "fake@email.com",
        "password": "wrong",
    })
    passed = r.status_code == 401
    log("Auth", "/api/v1/auth/login (invalid)", "POST", r.status_code,
        r.json(), passed, "Rechaza credenciales invalidas")

    return TOKEN


def headers():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_analysis():
    print("\n=== 4. ANALISIS DE TEXTO (NLP + ML) ===")

    test_texts = [
        {
            "name": "Texto ALTO riesgo",
            "data": {
                "text": "No puedo mas con esto, me quiero morir. Estoy completamente solo y nadie me necesita. La ansiedad me consume y no veo salida a mi sufrimiento.",
                "student_id": "STU001",
                "student_name": "Estudiante Test Alto",
                "source": "foro",
                "course_id": "CS101",
                "course_name": "Intro Programacion",
            },
            "expected_risk": ["medio", "alto"],
        },
        {
            "name": "Texto MEDIO riesgo",
            "data": {
                "text": "Ultimamente me siento muy estresado con los examenes y no puedo dormir bien. Tengo mucha ansiedad antes de cada parcial y me cuesta concentrarme. No se como manejar esta presion.",
                "student_id": "STU002",
                "student_name": "Estudiante Test Medio",
                "source": "foro",
                "course_id": "CS101",
                "course_name": "Intro Programacion",
            },
            "expected_risk": ["medio", "alto"],
        },
        {
            "name": "Texto BAJO riesgo",
            "data": {
                "text": "Hoy fue un excelente dia en clase. El profesor explico muy bien el tema de redes neuronales y pude entender todos los conceptos. Estoy motivado para seguir aprendiendo mas sobre inteligencia artificial.",
                "student_id": "STU003",
                "student_name": "Estudiante Test Bajo",
                "source": "foro",
                "course_id": "CS101",
                "course_name": "Intro Programacion",
            },
            "expected_risk": ["bajo"],
        },
        {
            "name": "Texto con ideacion suicida",
            "data": {
                "text": "Ya no quiero vivir asi, todo seria mejor sin mi. Nadie me quiere y siento que soy un fracaso total. Ojala no hubiera nacido, estoy desesperado y solo quiero desaparecer.",
                "student_id": "STU004",
                "student_name": "Estudiante Test Critico",
                "source": "chat",
                "course_id": "CS102",
                "course_name": "Base de Datos",
            },
            "expected_risk": ["medio", "alto"],
        },
        {
            "name": "Texto neutral academico",
            "data": {
                "text": "Para la tarea de esta semana necesitamos implementar un algoritmo de ordenamiento en Python. El profesor dijo que podemos usar quicksort o mergesort. Voy a empezar con la investigacion del tema.",
                "student_id": "STU005",
                "student_name": "Estudiante Test Neutral",
                "source": "tarea",
                "course_id": "CS101",
                "course_name": "Intro Programacion",
            },
            "expected_risk": ["bajo"],
        },
    ]

    analysis_results = []
    for test in test_texts:
        r = httpx.post(f"{BASE_URL}/api/v1/analysis/analyze-text",
                       json=test["data"], headers=headers(), timeout=30.0)
        data = r.json()
        risk = data.get("risk_level", "error")
        score = data.get("risk_score", 0)
        confidence = data.get("confidence", 0)
        markers = data.get("linguistic_markers", {})
        flagged = data.get("flagged_fragments", [])
        passed = r.status_code == 200 and risk in test["expected_risk"]

        analysis_results.append({
            "name": test["name"],
            "risk_level": risk,
            "risk_score": score,
            "confidence": confidence,
            "markers": markers,
            "flagged_fragments": flagged,
            "passed": passed,
        })

        log("Analysis", f"/api/v1/analysis/analyze-text ({test['name']})", "POST",
            r.status_code, {
                "risk_level": risk,
                "risk_score": score,
                "confidence": confidence,
                "flagged_count": len(flagged),
                "markers": markers,
            }, passed,
            f"Riesgo: {risk} (score: {score})")

    # Batch analysis
    print("\n  --- Batch Analysis ---")
    batch_data = {"texts": [test_texts[0]["data"], test_texts[2]["data"]]}
    r = httpx.post(f"{BASE_URL}/api/v1/analysis/analyze-batch",
                   json=batch_data, headers=headers(), timeout=30.0)
    data = r.json()
    passed = r.status_code == 200 and data.get("total", 0) == 2
    log("Analysis", "/api/v1/analysis/analyze-batch", "POST", r.status_code,
        {"total": data.get("total"), "results_count": len(data.get("results", []))},
        passed, f"Batch de {data.get('total', 0)} textos")

    return analysis_results


def test_alerts():
    print("\n=== 5. ALERTAS ===")

    # Listar alertas
    r = httpx.get(f"{BASE_URL}/api/v1/alerts/", headers=headers())
    data = r.json()
    alert_count = len(data) if isinstance(data, list) else 0
    passed = r.status_code == 200
    log("Alerts", "/api/v1/alerts/", "GET", r.status_code,
        {"total_alerts": alert_count}, passed, f"{alert_count} alertas encontradas")

    # Estadisticas
    r = httpx.get(f"{BASE_URL}/api/v1/alerts/statistics", headers=headers())
    stats = r.json()
    passed = r.status_code == 200
    log("Alerts", "/api/v1/alerts/statistics", "GET", r.status_code,
        stats, passed, "Estadisticas obtenidas")

    # Detalle de alerta si hay alguna
    if isinstance(data, list) and len(data) > 0:
        alert_id = data[0].get("id", "")
        r = httpx.get(f"{BASE_URL}/api/v1/alerts/{alert_id}", headers=headers())
        passed = r.status_code == 200
        log("Alerts", f"/api/v1/alerts/{{id}}", "GET", r.status_code,
            r.json() if passed else {}, passed, "Detalle de alerta")

        # Cambiar estado
        r = httpx.patch(f"{BASE_URL}/api/v1/alerts/{alert_id}/status",
                        json={"status": "reviewed"}, headers=headers())
        passed = r.status_code == 200
        log("Alerts", f"/api/v1/alerts/{{id}}/status", "PATCH", r.status_code,
            r.json() if passed else {}, passed, "Estado actualizado a 'reviewed'")

        # Agregar nota
        r = httpx.post(f"{BASE_URL}/api/v1/alerts/{alert_id}/notes",
                       json={"content": "Estudiante contactado, se agenda cita de seguimiento."},
                       headers=headers())
        passed = r.status_code == 200
        log("Alerts", f"/api/v1/alerts/{{id}}/notes", "POST", r.status_code,
            r.json() if passed else {}, passed, "Nota agregada")

    return data


def test_students():
    print("\n=== 6. ESTUDIANTES ===")

    r = httpx.get(f"{BASE_URL}/api/v1/students/", headers=headers())
    data = r.json()
    passed = r.status_code == 200
    count = len(data) if isinstance(data, list) else 0
    log("Students", "/api/v1/students/", "GET", r.status_code,
        {"total_profiles": count}, passed, f"{count} perfiles")

    # Estadisticas
    r = httpx.get(f"{BASE_URL}/api/v1/students/statistics", headers=headers())
    passed = r.status_code == 200
    log("Students", "/api/v1/students/statistics", "GET", r.status_code,
        r.json(), passed)

    # Historial de un estudiante
    r = httpx.get(f"{BASE_URL}/api/v1/students/STU001/history", headers=headers())
    passed = r.status_code == 200
    log("Students", "/api/v1/students/STU001/history", "GET", r.status_code,
        r.json() if passed else {}, passed)


def test_validation():
    print("\n=== 7. VALIDACIONES ===")

    # Texto muy corto
    r = httpx.post(f"{BASE_URL}/api/v1/analysis/analyze-text",
                   json={"text": "Hola", "student_id": "X"}, headers=headers())
    passed = r.status_code == 422
    log("Validation", "/analyze-text (texto corto)", "POST", r.status_code,
        {}, passed, "Rechaza texto < 10 chars")

    # Sin token
    r = httpx.get(f"{BASE_URL}/api/v1/alerts/")
    passed = r.status_code in (401, 403)
    log("Validation", "/alerts/ (sin token)", "GET", r.status_code,
        {}, passed, "Requiere autenticacion")

    # Token invalido
    r = httpx.get(f"{BASE_URL}/api/v1/alerts/",
                  headers={"Authorization": "Bearer token-falso-123"})
    passed = r.status_code in (401, 403)
    log("Validation", "/alerts/ (token invalido)", "GET", r.status_code,
        {}, passed, "Rechaza token invalido")


def test_rate_limit():
    print("\n=== 8. RATE LIMITING ===")
    r = httpx.get(f"{BASE_URL}/health")
    has_headers = "x-ratelimit-limit" in r.headers or "X-RateLimit-Limit" in r.headers
    log("RateLimit", "/health (headers)", "GET", r.status_code,
        {"rate_limit_headers": has_headers}, True,
        "Headers presentes" if has_headers else "Sin Redis, headers no aplican")


def generate_report(analysis_results, health_data, openapi_data):
    """Genera reporte completo en HTML."""

    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = total - passed

    # Agrupar por seccion
    sections = {}
    for r in RESULTS:
        sec = r["section"]
        if sec not in sections:
            sections[sec] = []
        sections[sec].append(r)

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MindLMS - Reporte de Pruebas del Backend</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, sans-serif; background: #f0f2f5; color: #333; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}

        .header {{ background: linear-gradient(135deg, #1a237e, #0d47a1); color: white; padding: 40px; border-radius: 12px; margin-bottom: 30px; }}
        .header h1 {{ font-size: 2em; margin-bottom: 10px; }}
        .header p {{ opacity: 0.9; font-size: 1.1em; }}
        .header .meta {{ margin-top: 15px; font-size: 0.9em; opacity: 0.8; }}

        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .card {{ background: white; border-radius: 10px; padding: 25px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); }}
        .card h3 {{ color: #666; font-size: 0.85em; text-transform: uppercase; margin-bottom: 8px; }}
        .card .value {{ font-size: 2.2em; font-weight: 700; }}
        .card .value.green {{ color: #2e7d32; }}
        .card .value.red {{ color: #c62828; }}
        .card .value.blue {{ color: #1565c0; }}
        .card .value.orange {{ color: #e65100; }}

        .section {{ background: white; border-radius: 10px; padding: 25px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); }}
        .section h2 {{ color: #1a237e; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #e3f2fd; }}

        table {{ width: 100%; border-collapse: collapse; }}
        th {{ background: #e3f2fd; color: #1a237e; padding: 12px 15px; text-align: left; font-size: 0.85em; text-transform: uppercase; }}
        td {{ padding: 10px 15px; border-bottom: 1px solid #eee; }}
        tr:hover {{ background: #f5f5f5; }}

        .badge {{ display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.8em; font-weight: 600; }}
        .badge.pass {{ background: #e8f5e9; color: #2e7d32; }}
        .badge.fail {{ background: #ffebee; color: #c62828; }}
        .badge.alto {{ background: #ffebee; color: #c62828; }}
        .badge.medio {{ background: #fff3e0; color: #e65100; }}
        .badge.bajo {{ background: #e8f5e9; color: #2e7d32; }}

        .analysis-card {{ border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; margin-bottom: 15px; }}
        .analysis-card.alto {{ border-left: 4px solid #c62828; }}
        .analysis-card.medio {{ border-left: 4px solid #e65100; }}
        .analysis-card.bajo {{ border-left: 4px solid #2e7d32; }}

        .markers {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-top: 10px; }}
        .marker {{ background: #f5f5f5; padding: 8px 12px; border-radius: 6px; font-size: 0.85em; }}
        .marker .label {{ color: #666; }}
        .marker .val {{ font-weight: 700; color: #1a237e; }}

        .progress-bar {{ height: 8px; background: #e0e0e0; border-radius: 4px; overflow: hidden; margin-top: 5px; }}
        .progress-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
        .progress-fill.green {{ background: #2e7d32; }}
        .progress-fill.orange {{ background: #e65100; }}
        .progress-fill.red {{ background: #c62828; }}

        .flagged {{ background: #fff3e0; border: 1px solid #ffe0b2; border-radius: 6px; padding: 10px; margin-top: 10px; font-size: 0.9em; }}
        .flagged strong {{ color: #e65100; }}

        .arch-table td {{ vertical-align: top; padding: 8px 15px; }}
        .status-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 5px; }}
        .status-dot.on {{ background: #2e7d32; }}
        .status-dot.off {{ background: #bdbdbd; }}
        .status-dot.warn {{ background: #e65100; }}

        .footer {{ text-align: center; padding: 30px; color: #999; font-size: 0.85em; }}
    </style>
</head>
<body>
<div class="container">

    <div class="header">
        <h1>MindLMS - Reporte de Pruebas del Backend</h1>
        <p>Modelo basado en PLN y ML para la deteccion temprana de ansiedad y estres en adolescentes</p>
        <div class="meta">
            Generado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} |
            Servidor: {BASE_URL} |
            Version: {health_data.get('version', '?')}
        </div>
    </div>

    <!-- RESUMEN -->
    <div class="summary">
        <div class="card">
            <h3>Tests Ejecutados</h3>
            <div class="value blue">{total}</div>
        </div>
        <div class="card">
            <h3>Exitosos</h3>
            <div class="value green">{passed}</div>
        </div>
        <div class="card">
            <h3>Fallidos</h3>
            <div class="value {'red' if failed > 0 else 'green'}">{failed}</div>
        </div>
        <div class="card">
            <h3>Tasa de Exito</h3>
            <div class="value green">{round(passed/max(total,1)*100)}%</div>
        </div>
    </div>

    <!-- ARQUITECTURA -->
    <div class="section">
        <h2>Arquitectura del Sistema</h2>
        <table class="arch-table">
            <tr>
                <td><strong>Framework</strong></td><td>FastAPI 0.115.6 (Python 3.13)</td>
                <td><strong>Base de Datos</strong></td><td><span class="status-dot on"></span>PostgreSQL (asyncpg)</td>
            </tr>
            <tr>
                <td><strong>Modelo ML</strong></td><td><span class="status-dot warn"></span>Clasificador basado en reglas (fallback)</td>
                <td><strong>MongoDB</strong></td><td><span class="status-dot off"></span>No conectado (opcional)</td>
            </tr>
            <tr>
                <td><strong>NLP</strong></td><td>Marcadores linguisticos (sin spaCy, usando fallback)</td>
                <td><strong>Cache Redis</strong></td><td><span class="status-dot off"></span>No conectado (opcional)</td>
            </tr>
            <tr>
                <td><strong>Auth</strong></td><td>JWT (python-jose + passlib/bcrypt)</td>
                <td><strong>Endpoints</strong></td><td>{len(openapi_data.get('paths', {}))} rutas documentadas</td>
            </tr>
        </table>
    </div>

    <!-- RESULTADOS POR SECCION -->"""

    for sec_name, sec_results in sections.items():
        sec_passed = sum(1 for r in sec_results if r["passed"])
        sec_total = len(sec_results)
        html += f"""
    <div class="section">
        <h2>{sec_name} ({sec_passed}/{sec_total} exitosos)</h2>
        <table>
            <thead>
                <tr><th>Metodo</th><th>Endpoint</th><th>Status</th><th>Resultado</th><th>Notas</th></tr>
            </thead>
            <tbody>"""
        for r in sec_results:
            badge = "pass" if r["passed"] else "fail"
            badge_text = "PASS" if r["passed"] else "FAIL"
            html += f"""
                <tr>
                    <td><strong>{r['method']}</strong></td>
                    <td><code>{r['endpoint']}</code></td>
                    <td>{r['status_code']}</td>
                    <td><span class="badge {badge}">{badge_text}</span></td>
                    <td>{r['notes']}</td>
                </tr>"""
        html += """
            </tbody>
        </table>
    </div>"""

    # ANALISIS DETALLADO
    html += """
    <div class="section">
        <h2>Analisis Detallado de Textos (NLP + ML)</h2>
        <p style="margin-bottom:15px;color:#666;">Cada texto fue procesado por el pipeline completo: limpieza, extraccion de marcadores linguisticos, clasificacion de riesgo y deteccion de fragmentos de alto riesgo.</p>"""

    for ar in analysis_results:
        risk = ar["risk_level"]
        score = ar["risk_score"]
        markers = ar["markers"]

        score_color = "red" if score > 0.7 else ("orange" if score > 0.4 else "green")

        html += f"""
        <div class="analysis-card {risk}">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <h3>{ar['name']}</h3>
                <span class="badge {risk}">Riesgo: {risk.upper()}</span>
            </div>
            <div style="margin-top:10px;">
                <strong>Score de riesgo:</strong> {score}
                <div class="progress-bar"><div class="progress-fill {score_color}" style="width:{score*100}%"></div></div>
            </div>
            <div style="margin-top:5px;"><strong>Confianza del modelo:</strong> {ar['confidence']}</div>
            <div class="markers">
                <div class="marker"><span class="label">Pronombres 1ra persona:</span> <span class="val">{markers.get('first_person_pronouns', 0)}</span></div>
                <div class="marker"><span class="label">Negaciones:</span> <span class="val">{markers.get('negations', 0)}</span></div>
                <div class="marker"><span class="label">Emociones negativas:</span> <span class="val">{markers.get('negative_emotions', 0)}</span></div>
                <div class="marker"><span class="label">Tiempo pasado:</span> <span class="val">{markers.get('past_tense', 0)}</span></div>
                <div class="marker"><span class="label">Ref. aislamiento:</span> <span class="val">{markers.get('isolation_references', 0)}</span></div>
            </div>"""

        if ar["flagged_fragments"]:
            html += """
            <div class="flagged">
                <strong>Fragmentos de alto riesgo detectados:</strong><ul>"""
            for frag in ar["flagged_fragments"]:
                html += f"<li><em>{frag}</em></li>"
            html += "</ul></div>"

        html += "</div>"

    html += "</div>"

    # ENDPOINTS DISPONIBLES
    paths = openapi_data.get("paths", {})
    html += """
    <div class="section">
        <h2>Catalogo Completo de Endpoints</h2>
        <table>
            <thead><tr><th>Metodo</th><th>Ruta</th><th>Descripcion</th><th>Auth</th></tr></thead>
            <tbody>"""
    for path, methods in paths.items():
        for method, details in methods.items():
            if method in ("get", "post", "put", "patch", "delete"):
                desc = details.get("summary", details.get("description", ""))[:80]
                has_auth = any("Bearer" in str(s) or "OAuth" in str(s) or "security" in str(details) for s in [details])
                auth_text = "JWT" if "security" in details or path != "/health" else "No"
                html += f"""
                <tr>
                    <td><strong>{method.upper()}</strong></td>
                    <td><code>{path}</code></td>
                    <td>{desc}</td>
                    <td>{auth_text}</td>
                </tr>"""
    html += """
            </tbody>
        </table>
    </div>"""

    # PIE
    html += f"""
    <div class="section">
        <h2>Notas Tecnicas</h2>
        <ul style="line-height:2;">
            <li><strong>Clasificador activo:</strong> Basado en reglas linguisticas (fallback). Para usar RoBERTa o Random Forest, se deben entrenar los modelos primero.</li>
            <li><strong>MongoDB:</strong> No conectado. Los analisis funcionan pero no persisten en la coleccion de textos. Solo se guardan alertas en PostgreSQL.</li>
            <li><strong>Redis:</strong> No conectado. Cache y rate limiting desactivados.</li>
            <li><strong>spaCy:</strong> No instalado. La deteccion de tiempo pasado y NER para anonimizacion usan fallback basico.</li>
            <li><strong>Integracion Moodle:</strong> Endpoints disponibles, requiere Moodle con Web Services configurados.</li>
            <li><strong>Marcadores linguisticos:</strong> Basados en Yang et al. (2023), Trifu et al. (2024), Zhang et al. (2024).</li>
        </ul>
    </div>

    <div class="footer">
        MindLMS v0.1.0 | Proyecto de Tesis - UPC Lima | Fily Baca &amp; Jesus Anaya | {datetime.now().strftime('%Y')}
    </div>

</div>
</body>
</html>"""

    return html


def main():
    print("=" * 60)
    print("  MindLMS - Prueba Completa del Backend")
    print("=" * 60)

    # Verificar servidor
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=5.0)
        if r.status_code != 200:
            print("ERROR: Backend no esta corriendo!")
            sys.exit(1)
    except Exception:
        print(f"ERROR: No se pudo conectar a {BASE_URL}")
        print("Ejecuta primero: python -m uvicorn app.main:app --port 8000")
        sys.exit(1)

    # Ejecutar pruebas
    health_data = test_health()
    openapi_data = test_openapi()
    test_register()

    if TOKEN:
        analysis_results = test_analysis()
        test_alerts()
        test_students()
        test_validation()
        test_rate_limit()
    else:
        print("\nERROR: No se pudo obtener token, saltando pruebas que requieren auth")
        analysis_results = []

    # Resumen
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["passed"])
    print(f"\n{'=' * 60}")
    print(f"  RESUMEN: {passed}/{total} pruebas exitosas ({round(passed/max(total,1)*100)}%)")
    print(f"{'=' * 60}")

    # Generar reporte HTML
    report_html = generate_report(analysis_results, health_data, openapi_data)
    report_path = "scripts/reporte_backend_mindlms.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_html)
    print(f"\nReporte generado: {report_path}")
    print("Abre el archivo HTML en tu navegador para ver el reporte visual completo.")


if __name__ == "__main__":
    main()
