const LABELS = {
  de: {
    search: 'Suche passende Datensätze …',
    searchDone: 'Datensatz «Hochwassergefahren» gefunden',
    fetch: 'Lade Gefahrenzonen für das Wallis …',
    fetchDone: '5 Gefahrenzonen geladen',
  },
  fr: {
    search: 'Recherche de jeux de données …',
    searchDone: 'Jeu de données «dangers de crues» trouvé',
    fetch: 'Chargement des zones de danger pour le Valais …',
    fetchDone: '5 zones de danger chargées',
  },
  it: {
    search: 'Ricerca di set di dati …',
    searchDone: 'Set di dati «pericoli di piena» trovato',
    fetch: 'Caricamento delle zone di pericolo per il Vallese …',
    fetchDone: '5 zone di pericolo caricate',
  },
  en: {
    search: 'Searching matching datasets …',
    searchDone: 'Found dataset “flood hazards”',
    fetch: 'Fetching hazard zones for Valais …',
    fetchDone: 'Fetched 5 hazard zones',
  },
};

const ANSWERS = {
  de: `## Hochwassergefahren im Wallis

In der Rhoneebene bestehen mehrere ausgewiesene Gefahrenzonen:

- **Sion & Martigny**: hohe Gefährdung (30-jährliches Ereignis)
- **Sierre & Visp**: mittlere Gefährdung (100-jährlich)
- **Brig-Glis**: geringe Restgefährdung

Die Zonen stammen aus dem Demo-Datensatz des Prototyps. Details zu den
offiziellen Gefahrenkarten finden Sie bei [BAFU](https://www.bafu.admin.ch).`,
  fr: `## Dangers de crues en Valais

Plusieurs zones de danger sont délimitées dans la plaine du Rhône :

- **Sion & Martigny** : danger élevé (crue trentennale)
- **Sierre & Viège** : danger moyen (crue centennale)
- **Brigue-Glis** : danger résiduel faible

Les zones proviennent du jeu de données de démonstration du prototype.
Détails sur les cartes officielles : [OFEV](https://www.bafu.admin.ch).`,
  it: `## Pericoli di piena in Vallese

Nella piana del Rodano sono delimitate diverse zone di pericolo:

- **Sion & Martigny**: pericolo elevato (evento trentennale)
- **Sierre & Visp**: pericolo medio (evento centennale)
- **Briga-Glis**: pericolo residuo basso

Le zone provengono dal set di dati dimostrativo del prototipo.
Dettagli sulle carte ufficiali: [UFAM](https://www.bafu.admin.ch).`,
  en: `## Flood hazards in Valais

Several designated hazard zones exist in the Rhone plain:

- **Sion & Martigny**: high hazard (30-year event)
- **Sierre & Visp**: medium hazard (100-year event)
- **Brig-Glis**: low residual hazard

The zones come from the prototype's demo dataset. Official hazard maps:
[FOEN](https://www.bafu.admin.ch).`,
};

const NAMES = {
  de: 'Hochwasser-Gefahrenzonen (Demo)',
  fr: 'Zones de danger de crues (démo)',
  it: 'Zone di pericolo di piena (demo)',
  en: 'Flood hazard zones (demo)',
};

export function floodScenario(lang, baseUrl) {
  const l = LABELS[lang] ?? LABELS.de;
  return [
    { delay: 400, event: { type: 'intermediate', step_id: 's1', status: 'started', label: l.search } },
    { delay: 900, event: { type: 'intermediate', step_id: 's1', status: 'finished', label: l.searchDone } },
    { delay: 300, event: { type: 'intermediate', step_id: 's2', status: 'started', label: l.fetch } },
    { delay: 1200, event: { type: 'intermediate', step_id: 's2', status: 'finished', label: l.fetchDone } },
    {
      delay: 500,
      event: {
        type: 'final',
        content_markdown: ANSWERS[lang] ?? ANSWERS.de,
        layers: [
          {
            id: 'demo-flood-valais',
            name: NAMES[lang] ?? NAMES.de,
            format: 'geojson',
            url: `${baseUrl}/data/flood-zones-valais.geojson`,
            geometry_type: 'polygon',
            feature_count: 5,
            bbox: [7.0, 46.05, 8.1, 46.35],
            attribution: 'SGS LLM demo data',
            style_hint: { fill_color: '#1c64f2', stroke_color: '#1e429f', opacity: 0.45 },
          },
        ],
      },
    },
  ];
}
