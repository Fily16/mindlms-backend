"""
Servicio completo de procesamiento de texto con PLN.
Limpieza, anonimización, tokenización con spaCy y extracción de marcadores lingüísticos.
Basado en: Yang et al. (2023), Trifu et al. (2024), Zhang et al. (2024).
"""

import re
from typing import List
from loguru import logger

try:
    import spacy
    nlp = spacy.load("es_core_news_sm")
    SPACY_AVAILABLE = True
except Exception as e:
    # Cualquier fallo cargando el modelo deja el sistema en el fallback por regex,
    # nunca tumba el arranque. En el contenedor de Modal, es_core_news_sm lanza
    # OverflowError("Python int too large to convert to C ssize_t") al deserializar
    # el tokenizador: antes ese error no estaba contemplado aquí y el proceso moría
    # al importar este módulo, con lo que toda la API quedaba caída.
    SPACY_AVAILABLE = False
    logger.warning(
        f"spaCy no disponible ({type(e).__name__}: {e}). "
        "Usando fallback para análisis lingüístico. La anonimización sigue "
        "activa por regex: correos, DNI, teléfonos y el nombre de quien se "
        "presenta en el texto (HU0033)."
    )

from app.schemas.analysis import LinguisticMarkers


# === Marcadores lingüísticos validados científicamente ===

FIRST_PERSON_PRONOUNS = {
    "yo", "me", "mi", "mí", "conmigo", "nos", "nosotros", "nosotras",
    "mío", "mía", "míos", "mías", "nuestro", "nuestra", "nuestros", "nuestras",
}

NEGATION_WORDS = {
    "no", "nunca", "jamás", "nada", "nadie", "ninguno", "ninguna",
    "tampoco", "ni", "sin", "ningún", "apenas",
}

NEGATIVE_EMOTION_WORDS = {
    # Tristeza
    "triste", "tristeza", "llorar", "llanto", "pena", "dolor", "sufrir", "sufrimiento",
    # Ansiedad
    "ansioso", "ansiosa", "ansiedad", "angustia", "angustiado", "angustiada",
    "nervioso", "nerviosa", "pánico", "tenso", "tensa",
    # Estrés
    "estrés", "estresado", "estresada", "agotado", "agotada", "agotamiento",
    "presión", "abrumado", "abrumada", "saturado", "saturada",
    # Depresión
    "deprimido", "deprimida", "depresión", "vacío", "vacía",
    "desesperado", "desesperada", "desesperanza", "desánimo",
    # Miedo
    "miedo", "temor", "terror", "asustado", "asustada",
    # Ira/Frustración
    "frustrado", "frustrada", "frustración", "odio", "rabia", "ira", "enojo",
    # Autoestima
    "inútil", "fracaso", "fracasado", "fracasada", "inseguro", "insegura",
    "incompetente", "torpe", "culpa", "culpable", "vergüenza",
    # Cansancio
    "cansado", "cansada", "agotado", "agotada", "exhausto", "exhausta",
    "aburrido", "aburrida", "harto", "harta",
    # Ideación (alto riesgo)
    "morir", "muerte", "suicidio", "matarme", "desaparecer",
    "no quiero vivir", "no vale la pena",
}

ISOLATION_WORDS = {
    "solo", "sola", "soledad", "aislado", "aislada", "aislamiento",
    "nadie", "abandonado", "abandonada", "abandono",
    "excluido", "excluida", "ignorado", "ignorada", "invisible",
    "rechazado", "rechazada", "marginado", "marginada",
    "incomprendido", "incomprendida", "desconectado", "desconectada",
}

HOPELESSNESS_WORDS = {
    "nunca", "imposible", "no puedo", "no sirve", "no vale", "rendirme",
    "sin sentido", "sin esperanza", "sin salida", "no hay solución",
    "para qué", "da igual", "no importa", "todo mal",
}

# Fragmentos de alto riesgo que deben ser flaggeados
HIGH_RISK_PATTERNS = [
    r"quiero\s+morir",
    r"no\s+quiero\s+vivir",
    r"me\s+quiero\s+matar",
    r"desaparecer",
    r"suicid",
    r"no\s+vale\s+la\s+pena",
    r"nadie\s+me\s+(quiere|importa|necesita)",
    r"estoy\s+solo\s+en\s+esto",
    r"no\s+puedo\s+más",
    r"no\s+aguanto\s+más",
    r"ojalá\s+no\s+(existiera|hubiera\s+nacido)",
    r"todo\s+sería\s+mejor\s+sin\s+mí",
]

# === Anonimización de nombres (HU0033) ===
# Regla propia para quien se presenta en el texto ("soy Juan Pérez"): debe
# funcionar aunque spaCy no esté disponible en el ambiente desplegado.
_NAME_INTRO_RE = re.compile(r"\b(me\s+llamo|mi\s+nombre\s+es|soy)\s+", re.IGNORECASE)
_NAME_TOKEN_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+(?:['-][A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)?")
_NAME_PARTICLES = {"de", "del", "la", "las", "los"}
_MAX_NAME_TOKENS = 4

# Nombres frecuentes: permiten reconocer un nombre escrito en minúsculas
# ("soy juan perez") sin confundirlo con "soy muy malo".
_COMMON_FIRST_NAMES = {
    "adriana", "alberto", "alejandra", "alejandro", "alex", "alicia", "andrea", "andres",
    "andrés", "angel", "ángel", "angela", "ángela", "ana", "antonio", "arturo", "beatriz",
    "camila", "carla", "carlos", "carmen", "cesar", "césar", "claudia", "cristian",
    "cristina", "daniel", "daniela", "david", "diana", "diego", "eduardo", "elena",
    "enrique", "esteban", "fernanda", "fernando", "francisco", "gabriel", "gabriela",
    "hector", "héctor", "hugo", "ivan", "iván", "jaime", "javier", "jesus", "jesús",
    "jorge", "jose", "josé", "juan", "julia", "julio", "karina", "laura", "lucia", "lucía",
    "luis", "manuel", "marco", "marcela", "maria", "maría", "mariana", "mario", "marta",
    "martin", "martín", "miguel", "monica", "mónica", "natalia", "nicolas", "nicolás",
    "oscar", "óscar", "pablo", "patricia", "paola", "pedro", "rafael", "raul", "raúl",
    "ricardo", "roberto", "rocio", "rocío", "rodrigo", "rosa", "sandra", "santiago",
    "sara", "sebastian", "sebastián", "sergio", "sofia", "sofía", "susana", "valeria",
    "veronica", "verónica", "victor", "víctor",
}

# Palabras que nunca forman parte de un nombre presentado.
_NOT_A_NAME = {
    # Conectores y palabras frecuentes
    "a", "al", "algo", "alguien", "aqui", "aquí", "asi", "así", "ayer", "bien", "como", "cómo",
    "con", "de", "del", "e", "el", "en", "esta", "está", "este", "esto", "hoy", "la", "las",
    "le", "lo", "los", "mal", "mas", "más", "mañana", "me", "mi", "mis", "mucho", "mucha",
    "muy", "nada", "ni", "no", "nunca", "o", "para", "pero", "por", "porque", "que", "qué",
    "se", "si", "sí", "siempre", "sin", "solo", "sola", "su", "tan", "tambien", "también",
    "tarde", "temprano", "todo", "toda", "todos", "tu", "un", "una", "uno", "y", "ya", "yo",
    # Verbos habituales tras presentarse
    "curso", "estoy", "estudio", "he", "necesito", "puedo", "quiero", "siento", "soy",
    "tengo", "trabajo", "vengo", "vivo",
    # Ocupaciones y adjetivos habituales tras "soy"
    "alumna", "alumno", "alumnos", "amiga", "amigo", "buen", "buena", "bueno", "compañera",
    "compañero", "delegada", "delegado", "docente", "estudiante", "estudiantes", "ingeniera",
    "ingeniero", "mala", "malo", "nueva", "nuevo", "persona", "peor", "profesor", "profesora",
    "responsable", "tutor", "tutora",
}

# Entidades que spaCy confunde con personas o lugares en textos de curso.
_NER_FALSE_POSITIVES = {"hola", "ref", "soy", "foro", "curso", "tarea", "examen", "examenes", "exámenes"}
_NER_COURSE_WORDS = {
    "algoritmos", "avanzada", "calculo", "cálculo", "diferencial", "fisica", "física",
    "ingles", "inglés", "matematica", "matemática", "programacion", "programación",
}


def _is_capitalized(token: str) -> bool:
    """Inicial mayúscula, sin ser un texto gritado en mayúsculas ("SOY PESIMO")."""
    return token[0].isupper() and not (len(token) > 1 and token.isupper())


def _is_ner_false_positive(entity: str) -> bool:
    """True si la entidad de spaCy es un saludo, una referencia o un curso, no un dato personal."""
    if "[" in entity or "]" in entity:
        return True
    words = [w.strip(".,;:!?¿¡").lower() for w in entity.split()]
    if not words or " ".join(words) in _NER_FALSE_POSITIVES:
        return True
    return any(w in _NER_COURSE_WORDS or w in _NER_FALSE_POSITIVES for w in words)


class TextProcessor:
    """Procesador de texto completo con spaCy y extracción de marcadores."""

    def clean_text(self, text: str) -> str:
        """Limpia y normaliza texto."""
        # Remover URLs
        text = re.sub(r"https?://\S+|www\.\S+", "", text)
        # Remover emails
        text = re.sub(r"\S+@\S+\.\S+", "[EMAIL]", text)
        # Remover números de teléfono
        text = re.sub(r"\b\d{9,}\b", "[TELEFONO]", text)
        # Remover emojis unicode
        text = re.sub(
            r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
            r"\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF]+",
            "", text
        )
        # Remover caracteres especiales excesivos, conservar puntuación básica
        text = re.sub(r"[^\w\s.,;:!?¿¡áéíóúñüÁÉÍÓÚÑÜ'\[\]-]", "", text)
        # Normalizar espacios
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def anonymize_text(self, text: str) -> str:
        """Anonimiza datos personales (cumplimiento Ley 29733)."""
        # Códigos de estudiante UPC
        text = re.sub(r"\b[uU]\d{9}\b", "[CODIGO]", text)
        # DNI peruano
        text = re.sub(r"\b\d{8}\b", "[DNI]", text)
        # Emails restantes
        text = re.sub(r"\S+@\S+\.\S+", "[EMAIL]", text)
        # Teléfonos
        text = re.sub(r"\b\d{9,}\b", "[TELEFONO]", text)
        # Nombres de quien se presenta en el texto (no depende de spaCy)
        text = self._mask_introduced_names(text)

        # NER con spaCy para nombres y locaciones
        if SPACY_AVAILABLE:
            doc = nlp(text)
            for ent in reversed(doc.ents):
                if _is_ner_false_positive(ent.text):
                    continue
                if ent.label_ == "PER":
                    text = text[:ent.start_char] + "[NOMBRE]" + text[ent.end_char:]
                elif ent.label_ == "LOC":
                    text = text[:ent.start_char] + "[LUGAR]" + text[ent.end_char:]
        return text

    def _mask_introduced_names(self, text: str) -> str:
        """Reemplaza por [NOMBRE] el nombre tras "soy", "me llamo" o "mi nombre es"."""
        result = []
        last = 0
        for intro in _NAME_INTRO_RE.finditer(text):
            if intro.start() < last:
                continue
            end = self._introduced_name_end(text, intro)
            if end is None:
                continue
            result.append(text[last:intro.end()])
            result.append("[NOMBRE]")
            last = end
        result.append(text[last:])
        return "".join(result)

    def _introduced_name_end(self, text: str, intro: re.Match) -> int | None:
        """Devuelve dónde termina el nombre presentado, o None si lo que sigue no es un nombre."""
        pos = intro.end()
        first = _NAME_TOKEN_RE.match(text, pos)
        if not first or first.group().lower() in _NOT_A_NAME:
            return None

        explicit = "nombre" in intro.group().lower()
        capitalized = _is_capitalized(first.group())
        if not (explicit or capitalized or first.group().lower() in _COMMON_FIRST_NAMES):
            return None

        end = first.end()
        count = 1
        while count < _MAX_NAME_TOKENS:
            gap = re.match(r"\s+", text[end:])
            if not gap:
                break
            token = _NAME_TOKEN_RE.match(text, end + gap.end())
            if not token:
                break
            word = token.group()
            lower = word.lower()
            if lower in _NAME_PARTICLES:
                # "de la Cruz": la partícula solo cuenta si sigue un apellido en mayúscula
                after = re.match(
                    r"(?:\s+(?:de|del|la|las|los))*\s+([A-ZÁÉÍÓÚÜÑ])", text[token.end():], re.IGNORECASE
                )
                if capitalized and after and after.group(1).isupper():
                    end = token.end()
                    count += 1
                    continue
                break
            if lower in _NOT_A_NAME or (capitalized and not _is_capitalized(word)):
                break
            end = token.end()
            count += 1
        return end

    def tokenize(self, text: str) -> List[str]:
        """Tokeniza texto con spaCy, removiendo stopwords y puntuación."""
        if SPACY_AVAILABLE:
            doc = nlp(text)
            return [token.lemma_.lower() for token in doc if not token.is_stop and not token.is_punct and len(token.text) > 1]
        return [w.lower() for w in text.split() if len(w) > 1]

    def extract_linguistic_markers(self, text: str) -> LinguisticMarkers:
        """
        Extrae marcadores lingüísticos validados científicamente.
        Basado en Yang et al. (2023) y Trifu et al. (2024).
        """
        words = text.lower().split()
        total_words = max(len(words), 1)

        # Conteo de marcadores por categoría
        first_person = sum(1 for w in words if w in FIRST_PERSON_PRONOUNS) / total_words
        negations = sum(1 for w in words if w in NEGATION_WORDS) / total_words
        negative_emotions = sum(1 for w in words if w in NEGATIVE_EMOTION_WORDS) / total_words
        isolation = sum(1 for w in words if w in ISOLATION_WORDS) / total_words

        # Detección de tiempo pasado con spaCy
        past_tense = 0.0
        if SPACY_AVAILABLE:
            doc = nlp(text)
            verbs = [t for t in doc if t.pos_ == "VERB"]
            if verbs:
                past_verbs = [t for t in verbs if "Past" in t.morph.get("Tense", [])]
                past_tense = len(past_verbs) / max(len(verbs), 1)

        return LinguisticMarkers(
            first_person_pronouns=round(first_person, 4),
            negations=round(negations, 4),
            negative_emotions=round(negative_emotions, 4),
            past_tense=round(past_tense, 4),
            isolation_references=round(isolation, 4),
        )

    def extract_matched_words(self, text: str) -> dict:
        """
        Devuelve las palabras EXACTAS del texto que activaron cada
        categoría de marcadores.  Usado por el AnalysisTheater para
        mostrar al psicólogo qué palabras concretas llevaron a la
        clasificación (evidencia trazable, no un score abstracto).

        Diccionario:
            first_person: ["me", "mi", ...]
            negations:    ["no", "nunca", ...]
            emotions:     ["ansiedad", "estresado", ...]
            isolation:    ["solo", "nadie", ...]
            hopelessness: ["no puedo", "sin sentido", ...]  # multi-palabra
        """
        text_lower = text.lower()
        words = text_lower.split()

        def match_set(word_set):
            # Preservar orden de aparición pero deduplicar
            seen = []
            for w in words:
                cleaned = w.strip(",.;:!?¿¡\"'()[]")
                if cleaned in word_set and cleaned not in seen:
                    seen.append(cleaned)
            return seen

        def match_multiword(word_set):
            # Frases con espacio: buscar como substring
            found = []
            for phrase in word_set:
                if " " in phrase and phrase in text_lower and phrase not in found:
                    found.append(phrase)
            return found

        return {
            "first_person": match_set(FIRST_PERSON_PRONOUNS),
            "negations": match_set(NEGATION_WORDS),
            "emotions": match_set(NEGATIVE_EMOTION_WORDS)
                        + match_multiword(NEGATIVE_EMOTION_WORDS),
            "isolation": match_set(ISOLATION_WORDS),
            "hopelessness": match_set(HOPELESSNESS_WORDS)
                            + match_multiword(HOPELESSNESS_WORDS),
        }

    def detect_high_risk_fragments(self, text: str) -> List[str]:
        """Detecta fragmentos de alto riesgo (ideación suicida, desesperanza severa)."""
        text_lower = text.lower()
        flagged = []
        for pattern in HIGH_RISK_PATTERNS:
            matches = re.finditer(pattern, text_lower)
            for m in matches:
                # Extraer contexto: 30 chars antes y después
                start = max(0, m.start() - 30)
                end = min(len(text_lower), m.end() + 30)
                fragment = "..." + text_lower[start:end] + "..."
                flagged.append(fragment)
        return flagged

    def compute_composite_risk_score(self, markers: LinguisticMarkers, flagged_fragments: List[str]) -> float:
        """
        Calcula un score de riesgo compuesto basado en marcadores lingüísticos.
        Este score complementa (no reemplaza) al modelo ML.
        """
        score = 0.0

        # Pesos basados en evidencia científica
        score += markers.first_person_pronouns * 1.5   # Yang et al., 2023
        score += markers.negations * 2.0                # Trifu et al., 2024
        score += markers.negative_emotions * 3.0        # Zhang et al., 2024
        score += markers.past_tense * 1.0
        score += markers.isolation_references * 2.5

        # Bonus por fragmentos de alto riesgo
        if flagged_fragments:
            score += len(flagged_fragments) * 0.15

        # Normalizar a [0, 1]
        return min(score, 1.0)
