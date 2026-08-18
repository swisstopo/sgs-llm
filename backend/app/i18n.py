"""Localized strings for the events the backend emits.

Progress labels and error text are ours, not the model's, so they need their own
translations. Romansh falls back to German here - the same choice mock-agent makes
(mock-agent/server.mjs) - while the model's actual answer is still produced in
Romansh when asked.
"""

from __future__ import annotations

from .protocol import DEFAULT_LANG, ProtocolLang

CANCELLED = {
    "de": "Anfrage abgebrochen.",
    "fr": "Requête annulée.",
    "it": "Richiesta annullata.",
    "en": "Request cancelled.",
}

TIMED_OUT = {
    "de": "Die Anfrage hat zu lange gedauert.",
    "fr": "La requête a pris trop de temps.",
    "it": "La richiesta ha richiesto troppo tempo.",
    "en": "The request took too long.",
}

INTERNAL = {
    "de": "Interner Fehler bei der Bearbeitung der Anfrage.",
    "fr": "Erreur interne lors du traitement de la requête.",
    "it": "Errore interno durante l'elaborazione della richiesta.",
    "en": "Internal error while handling the request.",
}

MCP_NOT_CONFIGURED = {
    "de": (
        "Der Chat ist noch nicht mit dem Geodaten-Dienst verbunden und kann daher keine "
        "Fragen beantworten. Die Karte lässt sich weiterhin uneingeschränkt nutzen."
    ),
    "fr": (
        "Le chat n'est pas encore connecté au service de géodonnées et ne peut donc pas "
        "répondre. La carte reste entièrement utilisable."
    ),
    "it": (
        "La chat non è ancora collegata al servizio di geodati e non può quindi "
        "rispondere. La mappa resta completamente utilizzabile."
    ),
    "en": (
        "The chat is not yet connected to the geodata service and cannot answer "
        "questions. The map remains fully usable."
    ),
}

TOO_MANY = {
    "de": "Zu viele Anfragen. Bitte kurz warten.",
    "fr": "Trop de requêtes. Veuillez patienter un instant.",
    "it": "Troppe richieste. Attendere un momento.",
    "en": "Too many requests. Please wait a moment.",
}

INTERLEAVED = {
    "de": "Es läuft noch eine Anfrage. Bitte warten Sie, bis sie beendet ist.",
    "fr": "Une requête est encore en cours. Veuillez attendre qu'elle se termine.",
    "it": "Una richiesta è ancora in corso. Attendere che finisca.",
    "en": "A request is still running. Please wait for it to finish.",
}

TOO_LONG = {
    "de": "Die Nachricht ist zu lang.",
    "fr": "Le message est trop long.",
    "it": "Il messaggio è troppo lungo.",
    "en": "The message is too long.",
}

THINKING = {
    "de": "Analysiere die Frage …",
    "fr": "Analyse de la question …",
    "it": "Analisi della domanda …",
    "en": "Analysing the question …",
}

ANSWERING = {
    "de": "Formuliere die Antwort …",
    "fr": "Rédaction de la réponse …",
    "it": "Redazione della risposta …",
    "en": "Composing the answer …",
}

TOOL_FAILED = {
    "de": "Schritt fehlgeschlagen",
    "fr": "Étape échouée",
    "it": "Passaggio non riuscito",
    "en": "Step failed",
}

# Keyed by MCP tool name. An unknown tool falls back to a generic label plus the raw
# name, so a tool we have not seen never renders as a blank progress step.
TOOL_RUNNING = {
    "search_layers": {
        "de": "Suche passende Datensätze …",
        "fr": "Recherche de jeux de données …",
        "it": "Ricerca di set di dati …",
        "en": "Searching matching datasets …",
    },
    "search_locations": {
        "de": "Bestimme den Ort …",
        "fr": "Localisation du lieu …",
        "it": "Individuazione del luogo …",
        "en": "Locating the place …",
    },
    "filter_features": {
        "de": "Lade Geodaten …",
        "fr": "Chargement des géodonnées …",
        "it": "Caricamento dei geodati …",
        "en": "Fetching geodata …",
    },
    "analyze_features": {
        "de": "Berechne Auswertung …",
        "fr": "Calcul de l'analyse …",
        "it": "Calcolo dell'analisi …",
        "en": "Computing the analysis …",
    },
    "geocode_location": {
        "de": "Suche Adresse oder Parzelle …",
        "fr": "Recherche de l'adresse ou de la parcelle …",
        "it": "Ricerca dell'indirizzo o della particella …",
        "en": "Resolving the address or parcel …",
    },
    "describe_layer": {
        "de": "Prüfe den Datensatz …",
        "fr": "Inspection du jeu de données …",
        "it": "Verifica del set di dati …",
        "en": "Inspecting the dataset …",
    },
    "identify_at_point": {
        "de": "Frage Daten am Standort ab …",
        "fr": "Interrogation des données à cet emplacement …",
        "it": "Interrogazione dei dati nella posizione …",
        "en": "Querying data at the location …",
    },
    "display_layer": {
        "de": "Bereite Kartenebene vor …",
        "fr": "Préparation de la couche …",
        "it": "Preparazione del livello …",
        "en": "Preparing the map layer …",
    },
    "display_catalog_layer": {
        "de": "Füge amtliche Kartenebene hinzu …",
        "fr": "Ajout de la couche officielle …",
        "it": "Aggiunta del livello ufficiale …",
        "en": "Adding the official map layer …",
    },
    "display_division": {
        "de": "Zeichne die Gebietsgrenze …",
        "fr": "Tracé de la limite territoriale …",
        "it": "Tracciamento del confine …",
        "en": "Drawing the boundary …",
    },
}

GENERIC_TOOL = {
    "de": "Führe Werkzeug aus",
    "fr": "Exécution de l'outil",
    "it": "Esecuzione dello strumento",
    "en": "Running tool",
}


def _pick(table: dict[str, str], lang: ProtocolLang) -> str:
    return table.get(lang) or table[DEFAULT_LANG]


def cancelled(lang: ProtocolLang) -> str:
    return _pick(CANCELLED, lang)


def timed_out(lang: ProtocolLang) -> str:
    return _pick(TIMED_OUT, lang)


def internal(lang: ProtocolLang) -> str:
    return _pick(INTERNAL, lang)


def too_many(lang: ProtocolLang) -> str:
    return _pick(TOO_MANY, lang)


def mcp_not_configured(lang: ProtocolLang) -> str:
    return _pick(MCP_NOT_CONFIGURED, lang)


def too_long(lang: ProtocolLang) -> str:
    return _pick(TOO_LONG, lang)


def interleaved(lang: ProtocolLang) -> str:
    return _pick(INTERLEAVED, lang)


def thinking(lang: ProtocolLang) -> str:
    return _pick(THINKING, lang)


def answering(lang: ProtocolLang) -> str:
    return _pick(ANSWERING, lang)


def tool_running(tool: str, lang: ProtocolLang) -> str:
    table = TOOL_RUNNING.get(tool)
    if table is not None:
        return _pick(table, lang)
    return f"{_pick(GENERIC_TOOL, lang)}: {tool}"


def tool_failed(lang: ProtocolLang) -> str:
    return _pick(TOOL_FAILED, lang)
