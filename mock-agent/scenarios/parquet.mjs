const ANSWERS = {
  de: `Dieses Szenario liefert absichtlich einen **GeoParquet**-Layer, um das
Verhalten des Clients bei noch nicht unterstützten Formaten zu testen.`,
  fr: `Ce scénario fournit volontairement une couche **GeoParquet** pour tester
le comportement du client avec des formats pas encore pris en charge.`,
  it: `Questo scenario fornisce volutamente un layer **GeoParquet** per testare
il comportamento del client con formati non ancora supportati.`,
  en: `This scenario intentionally returns a **GeoParquet** layer to exercise
the client's handling of not-yet-supported formats.`,
};

export function parquetScenario(lang, baseUrl) {
  return [
    {
      delay: 500,
      event: {
        type: 'final',
        content_markdown: ANSWERS[lang] ?? ANSWERS.de,
        layers: [
          {
            id: 'demo-parquet',
            name: 'GeoParquet sample',
            format: 'parquet',
            url: `${baseUrl}/data/sample.parquet`,
            geometry_type: 'point',
            feature_count: 1000,
          },
        ],
      },
    },
  ];
}
