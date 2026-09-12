-- ============================================================
-- MindLMS - Schema completo para PostgreSQL
-- Pegar en pgAdmin → Query Tool → Ejecutar (F5)
-- ============================================================
-- NOTA: Las tablas "users", "alerts" y "alert_notes" ya existen
-- en tu backend (SQLAlchemy las crea). Este script las incluye
-- con IF NOT EXISTS para que no falle si ya están creadas.
-- ============================================================

-- === TIPOS ENUMERADOS ===

DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('psicologo', 'admin', 'viewer');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE risk_level AS ENUM ('bajo', 'medio', 'alto');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE alert_status AS ENUM ('pendiente', 'revisada', 'en_seguimiento', 'resuelta');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE text_source AS ENUM ('foro', 'chat', 'tarea', 'cuestionario');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE intervention_type AS ENUM (
        'seguimiento_periodico',
        'entrevista_presencial',
        'derivacion_especialista',
        'contacto_tutor',
        'aplicacion_instrumento'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE intervention_status AS ENUM ('programada', 'en_curso', 'completada', 'cancelada');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE audit_action AS ENUM (
        'login', 'logout',
        'alert_viewed', 'alert_status_changed', 'alert_assigned',
        'note_added', 'intervention_created', 'intervention_updated',
        'analysis_executed', 'student_profile_viewed',
        'report_generated', 'data_exported'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;


-- ============================================================
-- 1. USUARIOS (ya existe en tu backend)
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id          VARCHAR PRIMARY KEY,
    email       VARCHAR UNIQUE NOT NULL,
    hashed_password VARCHAR NOT NULL,
    full_name   VARCHAR NOT NULL,
    role        user_role NOT NULL DEFAULT 'viewer',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);


-- ============================================================
-- 2. ESTUDIANTES (sincronizados desde Moodle)
-- ============================================================
CREATE TABLE IF NOT EXISTS students (
    id              VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    moodle_user_id  INTEGER UNIQUE NOT NULL,
    anonymous_id    VARCHAR UNIQUE NOT NULL,
    first_name      VARCHAR,
    last_name       VARCHAR,
    email           VARCHAR,
    current_risk_level  risk_level DEFAULT 'bajo',
    avg_risk_score      FLOAT DEFAULT 0.0,
    total_analyses      INTEGER DEFAULT 0,
    total_alerts        INTEGER DEFAULT 0,
    last_analyzed_at    TIMESTAMP,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_students_moodle_id ON students(moodle_user_id);
CREATE INDEX IF NOT EXISTS idx_students_risk ON students(current_risk_level);
CREATE INDEX IF NOT EXISTS idx_students_anonymous ON students(anonymous_id);


-- ============================================================
-- 3. CURSOS (sincronizados desde Moodle)
-- ============================================================
CREATE TABLE IF NOT EXISTS courses (
    id              VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    moodle_course_id INTEGER UNIQUE NOT NULL,
    short_name      VARCHAR NOT NULL,
    full_name       VARCHAR NOT NULL,
    category        VARCHAR,
    is_monitored    BOOLEAN NOT NULL DEFAULT TRUE,
    synced_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_courses_moodle_id ON courses(moodle_course_id);


-- ============================================================
-- 4. MATRICULAS: Estudiante <-> Curso (muchos a muchos)
-- ============================================================
CREATE TABLE IF NOT EXISTS student_courses (
    id          VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    student_id  VARCHAR NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    course_id   VARCHAR NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    enrolled_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(student_id, course_id)
);

CREATE INDEX IF NOT EXISTS idx_sc_student ON student_courses(student_id);
CREATE INDEX IF NOT EXISTS idx_sc_course ON student_courses(course_id);


-- ============================================================
-- 5. ALERTAS (ya existe en tu backend, ampliada con FKs)
-- ============================================================
CREATE TABLE IF NOT EXISTS alerts (
    id              VARCHAR PRIMARY KEY,
    student_id      VARCHAR NOT NULL,
    student_name    VARCHAR,
    course_id       VARCHAR,
    course_name     VARCHAR,
    risk_level      risk_level NOT NULL,
    risk_score      FLOAT NOT NULL,
    confidence      FLOAT NOT NULL,
    text_fragment   TEXT NOT NULL,
    source          VARCHAR NOT NULL,
    status          alert_status NOT NULL DEFAULT 'pendiente',
    assigned_to     VARCHAR REFERENCES users(id),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_student ON alerts(student_id);
CREATE INDEX IF NOT EXISTS idx_alerts_risk ON alerts(risk_level);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);
CREATE INDEX IF NOT EXISTS idx_alerts_assigned ON alerts(assigned_to);


-- ============================================================
-- 6. NOTAS DE ALERTA (ya existe en tu backend)
-- ============================================================
CREATE TABLE IF NOT EXISTS alert_notes (
    id          VARCHAR PRIMARY KEY,
    alert_id    VARCHAR NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    author_id   VARCHAR NOT NULL REFERENCES users(id),
    author_name VARCHAR NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notes_alert ON alert_notes(alert_id);


-- ============================================================
-- 7. SESIONES DE ANALISIS NLP/ML
-- ============================================================
CREATE TABLE IF NOT EXISTS analysis_sessions (
    id              VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    student_id      VARCHAR NOT NULL REFERENCES students(id),
    course_id       VARCHAR REFERENCES courses(id),
    source_type     text_source NOT NULL,
    original_hash   VARCHAR UNIQUE NOT NULL,
    cleaned_text    TEXT NOT NULL,
    risk_level      risk_level NOT NULL,
    risk_score      FLOAT NOT NULL,
    confidence      FLOAT NOT NULL,
    model_version   VARCHAR NOT NULL,
    processing_time_ms  INTEGER,
    alert_id        VARCHAR REFERENCES alerts(id),
    analyzed_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analysis_student ON analysis_sessions(student_id);
CREATE INDEX IF NOT EXISTS idx_analysis_risk ON analysis_sessions(risk_level);
CREATE INDEX IF NOT EXISTS idx_analysis_date ON analysis_sessions(analyzed_at);
CREATE INDEX IF NOT EXISTS idx_analysis_hash ON analysis_sessions(original_hash);
CREATE INDEX IF NOT EXISTS idx_analysis_model ON analysis_sessions(model_version);


-- ============================================================
-- 8. MARCADORES LINGUISTICOS POR SESION DE ANALISIS
-- ============================================================
CREATE TABLE IF NOT EXISTS linguistic_markers (
    id                      VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    analysis_session_id     VARCHAR NOT NULL REFERENCES analysis_sessions(id) ON DELETE CASCADE,
    first_person_pronouns   FLOAT NOT NULL DEFAULT 0.0,
    negations               FLOAT NOT NULL DEFAULT 0.0,
    negative_emotions       FLOAT NOT NULL DEFAULT 0.0,
    isolation_references    FLOAT NOT NULL DEFAULT 0.0,
    hopelessness            FLOAT NOT NULL DEFAULT 0.0,
    high_risk_patterns      FLOAT NOT NULL DEFAULT 0.0,
    past_tense              FLOAT NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_markers_session ON linguistic_markers(analysis_session_id);


-- ============================================================
-- 9. FRAGMENTOS MARCADOS (flagged_fragments)
-- ============================================================
CREATE TABLE IF NOT EXISTS flagged_fragments (
    id                  VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    analysis_session_id VARCHAR NOT NULL REFERENCES analysis_sessions(id) ON DELETE CASCADE,
    fragment_text       TEXT NOT NULL,
    marker_type         VARCHAR NOT NULL,
    position_start      INTEGER,
    position_end        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_fragments_session ON flagged_fragments(analysis_session_id);


-- ============================================================
-- 10. INTERVENCIONES DEL PSICOLOGO
-- ============================================================
CREATE TABLE IF NOT EXISTS interventions (
    id              VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    alert_id        VARCHAR NOT NULL REFERENCES alerts(id),
    student_id      VARCHAR NOT NULL REFERENCES students(id),
    psychologist_id VARCHAR NOT NULL REFERENCES users(id),
    type            intervention_type NOT NULL,
    status          intervention_status NOT NULL DEFAULT 'programada',
    description     TEXT,
    scheduled_at    TIMESTAMP,
    completed_at    TIMESTAMP,
    outcome_notes   TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interv_alert ON interventions(alert_id);
CREATE INDEX IF NOT EXISTS idx_interv_student ON interventions(student_id);
CREATE INDEX IF NOT EXISTS idx_interv_psychologist ON interventions(psychologist_id);
CREATE INDEX IF NOT EXISTS idx_interv_status ON interventions(status);


-- ============================================================
-- 11. LOG DE AUDITORIA (Ley 29733 - trazabilidad)
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id          VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id     VARCHAR REFERENCES users(id),
    action      audit_action NOT NULL,
    entity_type VARCHAR,
    entity_id   VARCHAR,
    details     JSONB,
    ip_address  VARCHAR,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_date ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);


-- ============================================================
-- 12. CONFIGURACION DEL SISTEMA
-- ============================================================
CREATE TABLE IF NOT EXISTS system_config (
    key         VARCHAR PRIMARY KEY,
    value       JSONB NOT NULL,
    description VARCHAR,
    updated_by  VARCHAR REFERENCES users(id),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

INSERT INTO system_config (key, value, description) VALUES
    ('risk_thresholds', '{"high": 0.75, "medium": 0.45}', 'Umbrales de riesgo para clasificacion'),
    ('monitoring_enabled', 'true', 'Monitoreo activo de textos del LMS'),
    ('detection_pace_seconds', '40', 'Segundos entre analisis de textos nuevos'),
    ('model_version', '"baseline_rf_v1"', 'Version activa del modelo ML')
ON CONFLICT (key) DO NOTHING;


-- ============================================================
-- VISTAS UTILES (para el dashboard del psicologo)
-- ============================================================

-- Vista: Resumen de riesgo por estudiante
CREATE OR REPLACE VIEW v_student_risk_summary AS
SELECT
    s.id,
    s.anonymous_id,
    s.first_name,
    s.last_name,
    s.current_risk_level,
    s.avg_risk_score,
    s.total_analyses,
    s.total_alerts,
    s.last_analyzed_at,
    COUNT(DISTINCT a.id) FILTER (WHERE a.status = 'pendiente') AS pending_alerts,
    COUNT(DISTINCT i.id) FILTER (WHERE i.status IN ('programada', 'en_curso')) AS active_interventions
FROM students s
LEFT JOIN alerts a ON a.student_id = s.id
LEFT JOIN interventions i ON i.student_id = s.id
WHERE s.is_active = TRUE
GROUP BY s.id;


-- Vista: Distribucion de riesgo (para graficos del dashboard)
CREATE OR REPLACE VIEW v_risk_distribution AS
SELECT
    current_risk_level AS risk_level,
    COUNT(*) AS total_students,
    ROUND(AVG(avg_risk_score)::NUMERIC, 4) AS avg_score
FROM students
WHERE is_active = TRUE
GROUP BY current_risk_level;


-- Vista: Alertas recientes con datos del estudiante
CREATE OR REPLACE VIEW v_recent_alerts AS
SELECT
    a.id AS alert_id,
    a.risk_level,
    a.risk_score,
    a.confidence,
    a.text_fragment,
    a.source,
    a.status,
    a.created_at,
    s.anonymous_id,
    s.first_name || ' ' || s.last_name AS student_name,
    c.full_name AS course_name,
    u.full_name AS assigned_to_name
FROM alerts a
LEFT JOIN students s ON a.student_id = s.id
LEFT JOIN courses c ON a.course_id = c.id
LEFT JOIN users u ON a.assigned_to = u.id
ORDER BY a.created_at DESC;


-- ============================================================
-- FIN DEL SCHEMA
-- ============================================================
-- Tablas creadas: 12
-- Vistas creadas: 3
-- Tipos ENUM: 7
--
-- Para verificar: SELECT tablename FROM pg_tables WHERE schemaname = 'public';
-- Para ver vistas: SELECT viewname FROM pg_views WHERE schemaname = 'public';
