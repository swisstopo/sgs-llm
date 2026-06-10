const LABELS = {
  de: {
    search: 'Suche Solarpotenzial-Daten …',
    searchDone: 'Datensatz «Eignung Dächer» gefunden',
    fetch: 'Werte Dächer in Bern aus …',
    fetchDone: '8 Dächer ausgewertet',
  },
  fr: {
    search: 'Recherche des données solaires …',
    searchDone: 'Jeu de données «aptitude des toits» trouvé',
    fetch: 'Évaluation des toits à Berne …',
    fetchDone: '8 toits évalués',
  },
  it: {
    search: 'Ricerca dei dati solari …',
    searchDone: 'Set di dati «idoneità dei tetti» trovato',
    fetch: 'Valutazione dei tetti a Berna …',
    fetchDone: '8 tetti valutati',
  },
  en: {
    search: 'Searching solar potential data …',
    searchDone: 'Found dataset “roof suitability”',
    fetch: 'Evaluating roofs in Bern …',
    fetchDone: 'Evaluated 8 roofs',
  },
};

const ANSWERS = {
  de: `## Solarpotenzial in Bern

Von den untersuchten Dächern eignen sich **4 hervorragend** und **3 gut**
für Photovoltaik. Das grösste Potenzial hat das Dach an der
Wankdorffeldstrasse 102 mit rund **45 100 kWh/Jahr**.

| Eignung | Anzahl |
| --- | --- |
| Hervorragend | 4 |
| Gut | 3 |
| Mittel | 1 |`,
  fr: `## Potentiel solaire à Berne

Parmi les toits analysés, **4 conviennent parfaitement** et **3 bien**
au photovoltaïque. Le plus grand potentiel : Wankdorffeldstrasse 102,
environ **45 100 kWh/an**.

| Aptitude | Nombre |
| --- | --- |
| Excellente | 4 |
| Bonne | 3 |
| Moyenne | 1 |`,
  it: `## Potenziale solare a Berna

Tra i tetti analizzati, **4 sono eccellenti** e **3 buoni** per il
fotovoltaico. Il potenziale maggiore: Wankdorffeldstrasse 102, circa
**45 100 kWh/anno**.

| Idoneità | Numero |
| --- | --- |
| Eccellente | 4 |
| Buona | 3 |
| Media | 1 |`,
  en: `## Solar potential in Bern

Of the analyzed roofs, **4 are excellent** and **3 good** for
photovoltaics. The biggest potential: Wankdorffeldstrasse 102 at about
**45,100 kWh/year**.

| Suitability | Count |
| --- | --- |
| Excellent | 4 |
| Good | 3 |
| Medium | 1 |`,
};

const NAMES = {
  de: 'Solareignung Dächer Bern (Demo)',
  fr: 'Aptitude solaire des toits, Berne (démo)',
  it: 'Idoneità solare dei tetti, Berna (demo)',
  en: 'Solar roof suitability, Bern (demo)',
};

export function solarScenario(lang, baseUrl) {
  const l = LABELS[lang] ?? LABELS.de;
  return [
    { delay: 400, event: { type: 'intermediate', step_id: 's1', status: 'started', label: l.search } },
    { delay: 800, event: { type: 'intermediate', step_id: 's1', status: 'finished', label: l.searchDone } },
    { delay: 300, event: { type: 'intermediate', step_id: 's2', status: 'started', label: l.fetch } },
    { delay: 1100, event: { type: 'intermediate', step_id: 's2', status: 'finished', label: l.fetchDone } },
    {
      delay: 400,
      event: {
        type: 'final',
        content_markdown: ANSWERS[lang] ?? ANSWERS.de,
        layers: [
          {
            id: 'demo-solar-bern',
            name: NAMES[lang] ?? NAMES.de,
            format: 'geojson',
            url: `${baseUrl}/data/solar-roofs-bern.geojson`,
            geometry_type: 'point',
            feature_count: 8,
            bbox: [7.42, 46.93, 7.48, 46.97],
            attribution: 'SGS LLM demo data',
            style_hint: { fill_color: '#f59e0b', stroke_color: '#92400e', point_radius: 8 },
          },
        ],
      },
    },
  ];
}
