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
except (ImportError, OSError):
    SPACY_AVAILABLE = False
    logger.warning("spaCy no disponible. Usando fallback para análisis lingüístico.")

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
        text = re.sub(r"[^\w\s.,;:!?¿¡áéíóúñüÁÉÍÓÚÑÜ'-]", "", text)
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

        # NER con spaCy para nombres y locaciones
        if SPACY_AVAILABLE:
            doc = nlp(text)
            for ent in reversed(doc.ents):
                if ent.label_ == "PER":
                    text = text[:ent.start_char] + "[NOMBRE]" + text[ent.end_char:]
                elif ent.label_ == "LOC":
                    text = text[:ent.start_char] + "[LUGAR]" + text[ent.end_char:]
        return text

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
