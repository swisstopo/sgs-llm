const LABELS = {
  de: { think: 'Analysiere Anfrage …', thinkDone: 'Anfrage verstanden' },
  fr: { think: 'Analyse de la requête …', thinkDone: 'Requête comprise' },
  it: { think: 'Analisi della richiesta …', thinkDone: 'Richiesta compresa' },
  en: { think: 'Analyzing request …', thinkDone: 'Request understood' },
};

const ANSWERS = {
  de: `Ich bin der **Mock-Agent** des SGS-LLM-Prototyps und beantworte erst
wenige Themen wirklich. Versuchen Sie zum Beispiel:

- *Hochwasser im Wallis* – zeigt Gefahrenzonen auf der Karte
- *Solarpotenzial in Bern* – zeigt geeignete Dächer

Als Kostprobe lege ich Ihnen einige Schweizer Städte auf die Karte.`,
  fr: `Je suis le **mock-agent** du prototype SGS LLM et je ne réponds pour
l'instant qu'à quelques sujets. Essayez par exemple :

- *crues en Valais* – affiche les zones de danger sur la carte
- *potentiel solaire à Berne* – affiche les toits adaptés

En guise d'aperçu, je place quelques villes suisses sur la carte.`,
  it: `Sono il **mock-agent** del prototipo SGS LLM e per ora rispondo solo
ad alcuni temi. Provi ad esempio:

- *piene in Vallese* – mostra le zone di pericolo sulla mappa
- *potenziale solare a Berna* – mostra i tetti adatti

Come assaggio, metto alcune città svizzere sulla mappa.`,
  en: `I am the **mock agent** of the SGS LLM prototype and only handle a few
topics so far. Try for example:

- *floods in Valais* – shows hazard zones on the map
- *solar potential in Bern* – shows suitable roofs

As a teaser, I'll put a few Swiss cities on the map.`,
};

const NAMES = {
  de: 'Schweizer Städte (Demo)',
  fr: 'Villes suisses (démo)',
  it: 'Città svizzere (demo)',
  en: 'Swiss cities (demo)',
};

export function defaultScenario(lang, baseUrl) {
  const l = LABELS[lang] ?? LABELS.de;
  return [
    { delay: 400, event: { type: 'intermediate', step_id: 's1', status: 'started', label: l.think } },
    { delay: 700, event: { type: 'intermediate', step_id: 's1', status: 'finished', label: l.thinkDone } },
    {
      delay: 400,
      event: {
        type: 'final',
        content_markdown: ANSWERS[lang] ?? ANSWERS.de,
        layers: [
          {
            id: 'demo-places',
            name: NAMES[lang] ?? NAMES.de,
            format: 'geojson',
            url: `${baseUrl}/data/sample-places.geojson`,
            geometry_type: 'point',
            feature_count: 5,
            bbox: [6.1, 46.0, 9.6, 47.4],
            attribution: 'SGS LLM demo data',
            style_hint: { fill_color: '#d8232a', stroke_color: '#7f1d1d', point_radius: 7 },
          },
        ],
      },
    },
  ];
}
