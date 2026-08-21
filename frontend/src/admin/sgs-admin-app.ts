import { LitElement, css, html, nothing } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { unsafeHTML } from 'lit/directives/unsafe-html.js';
import { SUPPORTED_LANGUAGES, changeLanguage, currentLanguage, t } from '../i18n/i18n';
import type { AppLanguage } from '../i18n/i18n';
import { renderMarkdown } from '../markdown/renderMarkdown';
import {
  GEODATA_EXPERIENCE_LEVELS,
  INTENDED_USES,
  USER_GROUPS,
} from '../onboarding/submitOnboarding';
import { adminFetch, logout, signIn } from './auth';
import type { AdminMetrics, AdminRecord, RecordPage } from './types';

type RecordKind = 'conversations' | 'profiles' | 'feedback';
const copy = {
  en: {
    admin: 'Administration',
    title: 'Usage overview',
    subtitle: 'Product activity and retained records',
    signIn: 'Sign in',
    signInTitle: 'Administrator access',
    signInBody: 'Use an administrator email address and password created in this application.',
    email: 'Email address',
    password: 'Password',
    authError: 'Invalid email address or password.',
    signOut: 'Sign out',
    refresh: 'Apply',
    from: 'From',
    to: 'To',
    messages: 'Messages',
    conversations: 'Conversations',
    conversationDetails: 'Full conversation',
    conversationId: 'Conversation ID',
    messageId: 'Message ID',
    started: 'Started',
    lastActivity: 'Last activity',
    language: 'Language',
    model: 'Model',
    tools: 'Tools',
    tokens: 'Tokens',
    layers: 'Layers',
    input: 'input',
    output: 'output',
    profiles: 'Surveys',
    feedback: 'Feedback',
    errors: 'Errors',
    latency: 'Latency',
    averageLatency: 'Average latency',
    totalLatency: 'Total latency',
    activity: 'Message activity',
    breakdowns: 'Usage details',
    records: 'Records',
    export: 'Export CSV',
    loadMore: 'Load more',
    empty: 'No records in this period.',
    profileNote: 'Survey responses are anonymous and cannot be linked to conversations.',
    surveyStatistics: 'Survey statistics',
    responses: 'responses',
    submitted: 'Submitted',
    userType: 'User type',
    geodataExperience: 'Geodata experience',
    intendedUse: 'Main purpose',
    consent: 'Consent',
    details: 'Open details',
    close: 'Close',
    metadata: 'Metadata',
    userMessage: 'Request from user',
    answer: 'Assistant answer',
    feedbackMessage: 'Feedback message',
    failed: 'The dashboard could not load. Check your access and try again.',
  },
  de: {
    admin: 'Administration',
    title: 'Nutzungsübersicht',
    subtitle: 'Produktaktivität und gespeicherte Einträge',
    signIn: 'Anmelden',
    signInTitle: 'Administratorzugang',
    signInBody: 'Verwenden Sie eine in dieser Anwendung erstellte E-Mail und ein Passwort.',
    email: 'E-Mail-Adresse',
    password: 'Passwort',
    authError: 'Ungültige E-Mail-Adresse oder ungültiges Passwort.',
    signOut: 'Abmelden',
    refresh: 'Anwenden',
    from: 'Von',
    to: 'Bis',
    messages: 'Nachrichten',
    conversations: 'Gespräche',
    conversationDetails: 'Vollständiges Gespräch',
    conversationId: 'Gesprächs-ID',
    messageId: 'Nachrichten-ID',
    started: 'Begonnen',
    lastActivity: 'Letzte Aktivität',
    language: 'Sprache',
    model: 'Modell',
    tools: 'Werkzeuge',
    tokens: 'Token',
    layers: 'Ebenen',
    input: 'Eingabe',
    output: 'Ausgabe',
    profiles: 'Umfragen',
    feedback: 'Feedback',
    errors: 'Fehler',
    latency: 'Latenz',
    averageLatency: 'Mittlere Latenz',
    totalLatency: 'Gesamtlatenz',
    activity: 'Nachrichtenaktivität',
    breakdowns: 'Nutzungsdetails',
    records: 'Einträge',
    export: 'CSV exportieren',
    loadMore: 'Mehr laden',
    empty: 'Keine Einträge in diesem Zeitraum.',
    profileNote: 'Umfrageantworten sind anonym und nicht mit Gesprächen verknüpfbar.',
    surveyStatistics: 'Umfragestatistik',
    responses: 'Antworten',
    submitted: 'Eingegangen',
    userType: 'Nutzertyp',
    geodataExperience: 'Geodatenkenntnisse',
    intendedUse: 'Hauptzweck',
    consent: 'Einwilligung',
    details: 'Details öffnen',
    close: 'Schliessen',
    metadata: 'Metadaten',
    userMessage: 'Anfrage des Nutzers',
    answer: 'Antwort des Assistenten',
    feedbackMessage: 'Feedback',
    failed: 'Die Übersicht konnte nicht geladen werden. Zugriff prüfen und erneut versuchen.',
  },
  fr: {
    admin: 'Administration',
    title: "Vue d'ensemble",
    subtitle: 'Activité du produit et données conservées',
    signIn: 'Se connecter',
    signInTitle: 'Accès administrateur',
    signInBody: "Utilisez une adresse e-mail et un mot de passe créés dans l'application.",
    email: 'Adresse e-mail',
    password: 'Mot de passe',
    authError: 'Adresse e-mail ou mot de passe incorrect.',
    signOut: 'Se déconnecter',
    refresh: 'Appliquer',
    from: 'Du',
    to: 'Au',
    messages: 'Messages',
    conversations: 'Conversations',
    conversationDetails: 'Conversation complète',
    conversationId: 'ID de conversation',
    messageId: 'ID du message',
    started: 'Début',
    lastActivity: 'Dernière activité',
    language: 'Langue',
    model: 'Modèle',
    tools: 'Outils',
    tokens: 'Jetons',
    layers: 'Couches',
    input: 'entrée',
    output: 'sortie',
    profiles: 'Enquêtes',
    feedback: 'Feedback',
    errors: 'Erreurs',
    latency: 'Latence',
    averageLatency: 'Latence moyenne',
    totalLatency: 'Latence totale',
    activity: 'Activité des messages',
    breakdowns: 'Détails d’utilisation',
    records: 'Données',
    export: 'Exporter CSV',
    loadMore: 'Charger plus',
    empty: 'Aucune donnée pour cette période.',
    profileNote: 'Les réponses sont anonymes et ne peuvent pas être liées aux conversations.',
    surveyStatistics: 'Statistiques de l’enquête',
    responses: 'réponses',
    submitted: 'Envoyé',
    userType: 'Type d’utilisateur',
    geodataExperience: 'Expérience en géodonnées',
    intendedUse: 'Objectif principal',
    consent: 'Consentement',
    details: 'Ouvrir les détails',
    close: 'Fermer',
    metadata: 'Métadonnées',
    userMessage: "Demande de l'utilisateur",
    answer: "Réponse de l'assistant",
    feedbackMessage: 'Feedback',
    failed: "Impossible de charger la vue d'ensemble. Vérifiez votre accès.",
  },
  it: {
    admin: 'Amministrazione',
    title: "Panoramica dell'utilizzo",
    subtitle: 'Attività del prodotto e dati conservati',
    signIn: 'Accedi',
    signInTitle: 'Accesso amministratore',
    signInBody: "Usa un'e-mail e una password create in questa applicazione.",
    email: 'Indirizzo e-mail',
    password: 'Password',
    authError: 'E-mail o password non valide.',
    signOut: 'Esci',
    refresh: 'Applica',
    from: 'Da',
    to: 'A',
    messages: 'Messaggi',
    conversations: 'Conversazioni',
    conversationDetails: 'Conversazione completa',
    conversationId: 'ID conversazione',
    messageId: 'ID messaggio',
    started: 'Inizio',
    lastActivity: 'Ultima attività',
    language: 'Lingua',
    model: 'Modello',
    tools: 'Strumenti',
    tokens: 'Token',
    layers: 'Livelli',
    input: 'input',
    output: 'output',
    profiles: 'Sondaggi',
    feedback: 'Feedback',
    errors: 'Errori',
    latency: 'Latenza',
    averageLatency: 'Latenza media',
    totalLatency: 'Latenza totale',
    activity: 'Attività dei messaggi',
    breakdowns: 'Dettagli di utilizzo',
    records: 'Dati',
    export: 'Esporta CSV',
    loadMore: 'Carica altro',
    empty: 'Nessun dato nel periodo.',
    profileNote: 'Le risposte sono anonime e non possono essere collegate alle conversazioni.',
    surveyStatistics: 'Statistiche del sondaggio',
    responses: 'risposte',
    submitted: 'Inviato',
    userType: 'Tipo di utente',
    geodataExperience: 'Esperienza con i geodati',
    intendedUse: 'Scopo principale',
    consent: 'Consenso',
    details: 'Apri dettagli',
    close: 'Chiudi',
    metadata: 'Metadati',
    userMessage: "Richiesta dell'utente",
    answer: "Risposta dell'assistente",
    feedbackMessage: 'Feedback',
    failed: 'Impossibile caricare la panoramica. Verifica il tuo accesso.',
  },
  rm: {
    admin: 'Administraziun',
    title: 'Survista dal diever',
    subtitle: 'Activitad dal product e datas conservadas',
    signIn: "S'annunziar",
    signInTitle: 'Access d’administraziun',
    signInBody: 'Utilisai ina adressa dad e-mail ed in pled-clav creà en questa applicaziun.',
    email: 'Adressa dad e-mail',
    password: 'Pled-clav',
    authError: 'Adressa dad e-mail u pled-clav nunvalid.',
    signOut: 'Sortir',
    refresh: 'Applitgar',
    from: 'Da',
    to: 'Fin',
    messages: 'Messadis',
    conversations: 'Conversaziuns',
    conversationDetails: 'Conversaziun cumpletta',
    conversationId: 'ID da la conversaziun',
    messageId: 'ID dal messadi',
    started: 'Cumenzà',
    lastActivity: 'Ultima activitad',
    language: 'Lingua',
    model: 'Model',
    tools: 'Utensils',
    tokens: 'Tokens',
    layers: 'Stresas',
    input: 'entrada',
    output: 'sortida',
    profiles: 'Retschertgas',
    feedback: 'Resuns',
    errors: 'Errors',
    latency: 'Latenza',
    averageLatency: 'Latenza media',
    totalLatency: 'Latenza totala',
    activity: 'Activitad dals messadis',
    breakdowns: 'Detagls dal diever',
    records: 'Datas',
    export: 'Exportar CSV',
    loadMore: 'Chargiar dapli',
    empty: 'Naginas datas en questa perioda.',
    profileNote: 'Las respostas èn anonimas e na pon betg vegnir colliadas cun conversaziuns.',
    surveyStatistics: 'Statistica da la retschertga',
    responses: 'respostas',
    submitted: 'Tramess',
    userType: 'Tip d’utilisader',
    geodataExperience: 'Experientscha cun geodatas',
    intendedUse: 'Intent principal',
    consent: 'Consentiment',
    details: 'Avrir detagls',
    close: 'Serrar',
    metadata: 'Metadatas',
    userMessage: 'Dumonda da l’utilisader',
    answer: 'Resposta da l’assistent',
    feedbackMessage: 'Resun',
    failed: 'La survista na po betg vegnir chargiada. Controllai vos access.',
  },
} as const;

@customElement('sgs-admin-app')
export class SgsAdminApp extends LitElement {
  static override styles = css`
    :host {
      display: block;
      min-height: 100dvh;
      background: #f5f6f7;
      color: var(--sgc-color-text, #1c2834);
      font-family: var(--sgc-font-family, Inter, sans-serif);
      font-size: 0.875rem;
    }
    * {
      box-sizing: border-box;
    }
    button,
    input,
    select {
      font: inherit;
    }
    button {
      cursor: pointer;
    }
    button:focus-visible,
    input:focus-visible,
    select:focus-visible {
      outline: 2px solid #d8232a;
      outline-offset: 2px;
    }
    .skip {
      position: fixed;
      left: 1rem;
      top: -4rem;
      z-index: 4;
      background: white;
      padding: 0.6rem;
    }
    .skip:focus {
      top: 0.5rem;
    }
    .topbar {
      position: sticky;
      top: 0;
      z-index: 3;
      height: 3.5rem;
      display: flex;
      align-items: center;
      gap: 1rem;
      padding: 0 1.25rem;
      background: #fff;
      border-bottom: 1px solid #d5dbe0;
    }
    .brand {
      font-size: 1rem;
      font-weight: 750;
      letter-spacing: -0.02em;
    }
    .brand b {
      color: #d8232a;
    }
    .section-name {
      border-left: 1px solid #d5dbe0;
      padding-left: 1rem;
      color: #5c6975;
      font-size: 0.8rem;
    }
    nav {
      margin-left: auto;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    select,
    input {
      min-height: 2rem;
      border: 1px solid #cbd2d8;
      border-radius: 0.25rem;
      background: #fff;
      color: inherit;
      padding: 0.35rem 0.5rem;
    }
    .button {
      min-height: 2rem;
      border: 1px solid #c8cfd5;
      border-radius: 0.25rem;
      background: #fff;
      color: #25323e;
      padding: 0.38rem 0.7rem;
      font-weight: 600;
      transition:
        background 140ms ease,
        border-color 140ms ease,
        transform 100ms ease;
    }
    .button:hover {
      background: #f0f2f4;
      border-color: #aeb8c0;
    }
    .button:active {
      transform: translateY(1px);
    }
    .button.primary {
      border-color: #d8232a;
      background: #d8232a;
      color: white;
    }
    .button.primary:hover {
      background: #be1c23;
    }
    .button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    main {
      max-width: 76rem;
      margin: 0 auto;
      padding: 2rem 1.5rem 4rem;
    }
    .page-heading {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 2rem;
      margin-bottom: 1.5rem;
    }
    h1 {
      margin: 0;
      font-size: 1.65rem;
      line-height: 1.15;
      letter-spacing: -0.035em;
      font-weight: 720;
    }
    .subtitle {
      margin: 0.35rem 0 0;
      color: #62707c;
      font-size: 0.84rem;
    }
    .date-form {
      display: flex;
      align-items: end;
      gap: 0.5rem;
    }
    .date-form label {
      display: grid;
      gap: 0.25rem;
      color: #62707c;
      font-size: 0.72rem;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      background: #fff;
      border: 1px solid #d8dde1;
      margin-bottom: 1rem;
    }
    .metric {
      min-height: 5.6rem;
      padding: 1rem 1.1rem;
      border-right: 1px solid #e1e5e8;
    }
    .metric:last-child {
      border-right: 0;
    }
    .metric span {
      color: #64717c;
      font-size: 0.73rem;
    }
    .metric strong {
      display: block;
      margin-top: 0.75rem;
      font-size: 1.45rem;
      line-height: 1;
      font-weight: 650;
      font-variant-numeric: tabular-nums;
    }
    .overview {
      display: grid;
      grid-template-columns: minmax(0, 1.8fr) minmax(16rem, 0.8fr);
      gap: 1rem;
      margin-bottom: 1rem;
    }
    .panel {
      background: #fff;
      border: 1px solid #d8dde1;
    }
    .panel-head {
      min-height: 3rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      padding: 0.7rem 1rem;
      border-bottom: 1px solid #e3e7ea;
    }
    h2 {
      margin: 0;
      font-size: 0.9rem;
      font-weight: 650;
    }
    .operational {
      color: #687581;
      font-size: 0.75rem;
      font-variant-numeric: tabular-nums;
    }
    .chart {
      height: 11rem;
      display: flex;
      align-items: end;
      gap: 0.45rem;
      padding: 1.25rem 1rem 0.6rem;
    }
    .bar-wrap {
      flex: 1;
      height: 100%;
      display: flex;
      align-items: end;
      position: relative;
      min-width: 3px;
    }
    .bar {
      width: 100%;
      min-height: 2px;
      background: #d8232a;
    }
    .bar-wrap:hover .tooltip {
      opacity: 1;
      transform: translate(-50%, 0);
    }
    .tooltip {
      position: absolute;
      left: 50%;
      bottom: calc(var(--height) + 0.35rem);
      transform: translate(-50%, 0.2rem);
      opacity: 0;
      pointer-events: none;
      white-space: nowrap;
      background: #24313c;
      color: white;
      padding: 0.3rem 0.42rem;
      font-size: 0.68rem;
      transition: 120ms ease;
    }
    .chart-axis {
      display: flex;
      justify-content: space-between;
      padding: 0 1rem 0.8rem;
      color: #7a8690;
      font-size: 0.68rem;
    }
    .breakdowns {
      padding: 1rem;
      display: grid;
      gap: 1rem;
    }
    .breakdown h3 {
      margin: 0 0 0.45rem;
      color: #6a7782;
      font-size: 0.7rem;
      font-weight: 600;
    }
    .rank {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 0.3rem 0.75rem;
      font-size: 0.78rem;
    }
    .rank > span:nth-child(odd) {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .rank .value {
      font-variant-numeric: tabular-nums;
      font-weight: 650;
    }
    .records-toolbar {
      display: flex;
      align-items: center;
      gap: 0.35rem;
    }
    .tabs {
      display: flex;
      align-items: center;
      gap: 0;
    }
    .tab {
      min-height: 2rem;
      border: 0;
      border-bottom: 2px solid transparent;
      background: none;
      padding: 0.35rem 0.7rem;
      color: #5f6c77;
      font-weight: 550;
    }
    .tab:hover {
      color: #1c2834;
    }
    .tab.active {
      border-bottom-color: #d8232a;
      color: #b8181f;
    }
    .export {
      margin-left: auto;
    }
    .note {
      margin: 0;
      padding: 0.65rem 1rem;
      border-bottom: 1px solid #e5e8eb;
      background: #fafbfb;
      color: #687581;
      font-size: 0.76rem;
    }
    .survey-statistics {
      border-bottom: 1px solid #e3e7ea;
      background: #fafbfb;
    }
    .survey-statistics-head {
      min-height: 2.75rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      padding: 0.65rem 1rem;
    }
    .survey-statistics-head h3 {
      margin: 0;
      color: #34424e;
      font-size: 0.78rem;
      font-weight: 650;
    }
    .survey-total {
      color: #64717c;
      font-size: 0.72rem;
      font-variant-numeric: tabular-nums;
    }
    .survey-histograms {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      border-top: 1px solid #e8ebed;
    }
    .survey-histogram {
      min-width: 0;
      padding: 0.85rem 1rem 1rem;
    }
    .survey-histogram + .survey-histogram {
      border-left: 1px solid #e3e7ea;
    }
    .survey-histogram h4 {
      min-height: 2rem;
      margin: 0 0 0.65rem;
      color: #53616d;
      font-size: 0.7rem;
      font-weight: 650;
      line-height: 1.4;
    }
    .histogram-rows {
      display: grid;
      gap: 0.55rem;
    }
    .histogram-label {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 0.75rem;
      margin-bottom: 0.22rem;
      color: #4d5b67;
      font-size: 0.7rem;
      line-height: 1.3;
    }
    .histogram-label span:first-child {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .histogram-count {
      flex: 0 0 auto;
      color: #25333e;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    .histogram-track {
      height: 0.35rem;
      overflow: hidden;
      background: #e4e8eb;
    }
    .histogram-bar {
      display: block;
      height: 100%;
      background: #d8232a;
    }
    .record-header,
    .record-row {
      display: grid;
      grid-template-columns: 10.5rem 4rem minmax(0, 1fr);
      align-items: center;
      column-gap: 1rem;
    }
    .conversation-grid {
      grid-template-columns: 10.5rem 4rem minmax(0, 1fr) 5.5rem;
    }
    .profile-table {
      overflow-x: auto;
      overscroll-behavior-inline: contain;
    }
    .profile-grid {
      min-width: 68rem;
      grid-template-columns:
        10.5rem 4rem minmax(10rem, 1fr) minmax(13rem, 1.25fr) minmax(13rem, 1.25fr)
        5rem;
    }
    .record-header {
      min-height: 2.3rem;
      padding: 0 1rem;
      color: #74808a;
      border-bottom: 1px solid #e3e7ea;
      font-size: 0.68rem;
    }
    .record-row {
      width: 100%;
      min-height: 3.5rem;
      padding: 0.6rem 1rem;
      border: 0;
      border-bottom: 1px solid #e8ebed;
      background: #fff;
      color: inherit;
      text-align: left;
    }
    .record-row:hover {
      background: #f8f9fa;
    }
    .conversation-list-item {
      border-bottom: 1px solid #e8ebed;
      background: #fff;
    }
    .conversation-list-item .record-row {
      border-bottom: 0;
      transition:
        background-color 160ms ease,
        box-shadow 160ms ease;
    }
    .conversation-list-item.expanded .record-row {
      background: #fff8f8;
      box-shadow: inset 3px 0 #d8232a;
    }
    .conversation-count {
      justify-self: end;
      display: inline-flex;
      align-items: center;
      gap: 0.6rem;
      color: #596773;
      font-size: 0.75rem;
      font-variant-numeric: tabular-nums;
    }
    .conversation-count b {
      font-weight: 650;
    }
    .disclosure {
      display: inline-block;
      color: #7a858e;
      font-size: 1rem;
      line-height: 1;
      transform: rotate(0deg);
      transition: transform 180ms ease;
    }
    .conversation-list-item.expanded .disclosure {
      transform: rotate(180deg);
    }
    .inline-transcript {
      padding: 1.1rem 1.5rem 1.8rem;
      border-top: 1px solid #e1e5e8;
      background: #fafbfb;
    }
    .thread-detail {
      width: min(48rem, calc(100% - 16.5rem));
      margin-left: 16.5rem;
    }
    .thread-overview {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 0.85rem 1.25rem;
      margin: 0 0 1.15rem;
      padding: 0 0 1.15rem;
      border-bottom: 1px solid #dce1e5;
    }
    .thread-overview > div,
    .turn-metadata > div {
      min-width: 0;
    }
    .thread-overview .wide {
      grid-column: 1 / -1;
    }
    .thread-overview dt,
    .turn-metadata dt {
      margin-bottom: 0.18rem;
      color: #74808a;
      font-size: 0.66rem;
      font-weight: 650;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }
    .thread-overview dd,
    .turn-metadata dd {
      color: #2d3a45;
      font-size: 0.75rem;
      line-height: 1.45;
    }
    .thread-overview code,
    .turn-metadata code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.7rem;
      user-select: all;
    }
    .record-row.selected {
      background: #fff5f5;
      box-shadow: inset 3px 0 #d8232a;
    }
    .record-row time {
      color: #596773;
      font-size: 0.75rem;
      font-variant-numeric: tabular-nums;
    }
    .lang {
      text-transform: uppercase;
      color: #6a7782;
      font-size: 0.7rem;
    }
    .record-copy {
      min-width: 0;
    }
    .record-copy strong {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 0.8rem;
      font-weight: 600;
    }
    .profile-cell {
      min-width: 0;
      overflow: hidden;
      color: #34424e;
      font-size: 0.78rem;
      font-weight: 550;
      line-height: 1.35;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .profile-consent {
      color: #63717c;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.7rem;
      font-weight: 500;
    }
    .empty {
      padding: 3rem 1rem;
      text-align: center;
      color: #71808c;
    }
    .load-more {
      display: flex;
      justify-content: center;
      padding: 0.8rem;
    }
    .error-banner {
      margin-bottom: 1rem;
      padding: 0.75rem 1rem;
      border-left: 3px solid #d8232a;
      background: #fff;
      color: #a4151b;
    }
    .skeleton {
      min-height: 5.5rem;
      background: linear-gradient(90deg, #fff 25%, #f0f2f4 50%, #fff 75%);
      background-size: 200% 100%;
      animation: shimmer 1.3s infinite linear;
    }
    @keyframes shimmer {
      to {
        background-position: -200% 0;
      }
    }
    .scrim {
      position: fixed;
      inset: 3.5rem 0 0;
      z-index: 4;
      border: 0;
      background: rgb(28 40 52 / 22%);
      padding: 0;
    }
    .drawer {
      position: fixed;
      z-index: 5;
      top: 3.5rem;
      right: 0;
      bottom: 0;
      width: min(34rem, calc(100vw - 2rem));
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      background: #fff;
      border-left: 1px solid #cfd5da;
      box-shadow: -12px 0 32px rgb(43 57 69 / 14%);
    }
    .drawer-head {
      display: flex;
      align-items: center;
      gap: 1rem;
      min-height: 3.6rem;
      padding: 0.7rem 1rem;
      border-bottom: 1px solid #dde2e5;
    }
    .drawer-head h2 {
      flex: 1;
    }
    .icon-button {
      width: 2rem;
      height: 2rem;
      border: 0;
      border-radius: 0.2rem;
      background: none;
      color: #50606c;
      font-size: 1.2rem;
    }
    .icon-button:hover {
      background: #f0f2f4;
    }
    .drawer-body {
      overflow-y: auto;
      padding: 1.25rem 1.25rem 3rem;
    }
    .drawer section {
      margin-bottom: 1.5rem;
    }
    .drawer h3 {
      margin: 0 0 0.65rem;
      color: #62707c;
      font-size: 0.72rem;
      font-weight: 650;
    }
    dl {
      display: grid;
      grid-template-columns: 8.5rem minmax(0, 1fr);
      gap: 0.45rem 1rem;
      margin: 0;
      font-size: 0.78rem;
    }
    dt {
      color: #6d7983;
    }
    dd {
      min-width: 0;
      margin: 0;
      overflow-wrap: anywhere;
      font-variant-numeric: tabular-nums;
    }
    .content-block {
      margin: 0;
      padding: 0.85rem;
      background: #f5f6f7;
      border-left: 2px solid #cbd2d8;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font: inherit;
      font-size: 0.8rem;
      line-height: 1.55;
    }
    .user-block {
      border-left-color: #d8232a;
      background: #fff;
    }
    .assistant-block {
      border-left-color: #9aa6af;
      background: #f0f2f4;
    }
    .markdown {
      white-space: normal;
    }
    .conversation-timeline {
      display: grid;
      gap: 0;
    }
    .conversation-timeline > h3 {
      margin: 0 0 0.65rem;
      color: #62707c;
      font-size: 0.72rem;
      font-weight: 650;
    }
    .conversation-turn {
      padding: 1rem 0;
      border-top: 1px solid #e4e8eb;
    }
    .conversation-turn:first-of-type {
      padding-top: 0.25rem;
      border-top: 0;
    }
    .turn-heading {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 0.75rem;
      color: #687581;
      font-size: 0.7rem;
    }
    .turn-metadata {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 0.65rem 1rem;
      margin: 0 0 0.9rem;
      padding: 0.75rem 0;
      border-top: 1px solid #edf0f2;
      border-bottom: 1px solid #edf0f2;
    }
    .turn-metadata .wide {
      grid-column: span 2;
    }
    .turn-metadata .error-value {
      color: #a4151b;
      font-weight: 650;
    }
    .conversation-turn h4 {
      margin: 0.8rem 0 0.35rem;
      color: #53616d;
      font-size: 0.72rem;
      font-weight: 650;
    }
    .markdown p {
      margin: 0 0 0.75rem;
    }
    .markdown p:last-child {
      margin-bottom: 0;
    }
    .markdown h1,
    .markdown h2,
    .markdown h3 {
      margin: 1rem 0 0.45rem;
      color: #24313c;
      font-size: 0.86rem;
    }
    .markdown ul,
    .markdown ol {
      margin: 0.5rem 0 0.85rem;
      padding-left: 1.25rem;
    }
    .markdown li {
      margin-bottom: 0.35rem;
    }
    .markdown a {
      color: #b8181f;
    }
    .login-shell {
      min-height: calc(100dvh - 3.5rem);
      display: grid;
      place-items: center;
      padding: 2rem;
    }
    .login {
      width: min(27rem, 100%);
      background: #fff;
      border: 1px solid #d5dbe0;
      padding: 1.75rem;
    }
    .login h1 {
      font-size: 1.35rem;
    }
    .login p {
      max-width: 55ch;
      color: #63717d;
      line-height: 1.55;
      margin: 0.7rem 0 1.35rem;
    }
    .login form {
      display: grid;
      gap: 0.85rem;
    }
    .login label {
      display: grid;
      gap: 0.35rem;
      color: #465562;
      font-size: 0.78rem;
      font-weight: 600;
    }
    .login input {
      width: 100%;
      min-height: 2.5rem;
    }
    .login .primary {
      width: 100%;
      min-height: 2.5rem;
    }
    .auth-error {
      margin: 0 !important;
      color: #a4151b !important;
      font-size: 0.76rem;
    }
    .configuration-note {
      margin-top: 0.9rem !important;
      color: #a4151b !important;
      font-size: 0.78rem;
    }
    @media (max-width: 760px) {
      main {
        padding: 1.35rem 0.85rem 3rem;
      }
      .page-heading {
        align-items: stretch;
        flex-direction: column;
        gap: 1rem;
      }
      .date-form {
        flex-wrap: wrap;
      }
      .summary {
        grid-template-columns: repeat(2, 1fr);
      }
      .metric:nth-child(2) {
        border-right: 0;
      }
      .metric:nth-child(-n + 2) {
        border-bottom: 1px solid #e1e5e8;
      }
      .overview {
        grid-template-columns: 1fr;
      }
      .survey-histograms {
        grid-template-columns: 1fr;
      }
      .survey-histogram + .survey-histogram {
        border-top: 1px solid #e3e7ea;
        border-left: 0;
      }
      .survey-histogram h4 {
        min-height: auto;
      }
      .record-header {
        display: none;
      }
      .record-row {
        grid-template-columns: 1fr auto;
        gap: 0.25rem 0.8rem;
      }
      .record-row time,
      .record-copy {
        grid-column: 1;
      }
      .lang {
        grid-column: 2;
        grid-row: 1;
      }
      .record-row.conversation-grid {
        grid-template-columns: minmax(0, 1fr) auto;
      }
      .profile-table .record-header.profile-grid,
      .profile-table .record-row.profile-grid {
        grid-template-columns:
          10.5rem 4rem minmax(10rem, 1fr) minmax(13rem, 1.25fr) minmax(13rem, 1.25fr)
          5rem;
      }
      .profile-table .record-header.profile-grid {
        display: grid;
      }
      .profile-table .profile-grid time,
      .profile-table .profile-grid .lang {
        grid-column: auto;
        grid-row: auto;
      }
      .conversation-count {
        grid-column: 2;
        grid-row: 2;
      }
      .inline-transcript {
        padding: 1rem 0.85rem 1.4rem;
      }
      .thread-detail {
        width: 100%;
        margin-left: 0;
      }
      .thread-overview,
      .turn-metadata {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .section-name {
        display: none;
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .button,
      .tooltip {
        transition: none;
      }
      .skeleton {
        animation: none;
      }
    }
  `;

  @state() private authenticated = false;
  @state() private loading = true;
  @state() private failed = false;
  @state() private metrics?: AdminMetrics;
  @state() private kind: RecordKind = 'conversations';
  @state() private records: AdminRecord[] = [];
  @state() private nextCursor: string | null = null;
  @state() private selected?: AdminRecord;
  @state() private expandedConversationId = '';
  @state() private from = this.isoDaysAgo(6);
  @state() private to = this.isoDaysAgo(0);
  @state() private authError = '';
  @state() private authSubmitting = false;

  private get text() {
    return copy[currentLanguage()];
  }

  override async connectedCallback(): Promise<void> {
    super.connectedCallback();
    try {
      this.authenticated = (await adminFetch('/me')).ok;
      if (this.authenticated) await this.loadAll();
    } catch {
      this.failed = true;
    } finally {
      this.loading = false;
    }
  }

  override render() {
    return html`<a class="skip" href="#admin-content">Skip to content</a
      >${this.renderHeader()}${this.loading
        ? this.renderLoading()
        : this.authenticated
          ? this.renderDashboard()
          : this.renderLogin()}${this.selected ? this.renderDrawer(this.selected) : nothing}`;
  }

  protected override updated(changed: Map<PropertyKey, unknown>): void {
    if (changed.has('selected') && this.selected) {
      this.renderRoot.querySelector<HTMLElement>('.drawer')?.focus();
    }
  }

  private renderHeader() {
    return html`<header class="topbar">
      <div class="brand"><b>SGS</b> LLM</div>
      <div class="section-name">${this.text.admin}</div>
      <nav>
        <select aria-label=${t('rail.language')} @change=${this.setLanguage}>
          ${SUPPORTED_LANGUAGES.map(
            (lang) =>
              html`<option value=${lang} ?selected=${lang === currentLanguage()}>
                ${lang.toUpperCase()}
              </option>`,
          )}</select
        >${this.authenticated
          ? html`<button class="button" @click=${this.signOut}>${this.text.signOut}</button>`
          : nothing}
      </nav>
    </header>`;
  }

  private renderLoading() {
    return html`<main><div class="skeleton"></div></main>`;
  }

  private renderLogin() {
    return html`<div class="login-shell">
      <section class="login">
        <h1>${this.text.signInTitle}</h1>
        <p>${this.text.signInBody}</p>
        ${this.renderAuthForm()}${this.failed
          ? html`<p class="configuration-note">${this.text.failed}</p>`
          : nothing}
      </section>
    </div>`;
  }

  private renderAuthForm() {
    return html`<form @submit=${this.submitAuthentication}>
      <label
        >${this.text.email}<input
          name="email"
          type="email"
          required
          autocomplete="username" /></label
      ><label
        >${this.text.password}<input
          name="password"
          type="password"
          required
          autocomplete="current-password" /></label
      >${this.renderAuthError()}<button class="button primary" ?disabled=${this.authSubmitting}>
        ${this.text.signIn}
      </button>
    </form>`;
  }

  private renderAuthError() {
    return this.authError
      ? html`<p class="auth-error" role="alert">${this.authError}</p>`
      : nothing;
  }

  private renderDashboard() {
    const totals = this.metrics?.totals ?? {};
    return html`<main id="admin-content">
      <div class="page-heading">
        <div>
          <h1>${this.text.title}</h1>
          <p class="subtitle">${this.text.subtitle}</p>
        </div>
        ${this.renderDateForm()}
      </div>
      ${this.failed
        ? html`<div class="error-banner" role="alert">${this.text.failed}</div>`
        : nothing}
      <section class="summary" aria-label="Summary">
        ${[
          [this.text.messages, totals.messages ?? 0],
          [this.text.conversations, totals.conversations ?? 0],
          [this.text.profiles, totals.onboarding ?? 0],
          [this.text.feedback, totals.feedback ?? 0],
        ].map(
          ([label, value]) =>
            html`<div class="metric"><span>${label}</span><strong>${value}</strong></div>`,
        )}
      </section>
      <div class="overview">
        <section class="panel">
          <header class="panel-head">
            <h2>${this.text.activity}</h2>
            <span class="operational"
              >${this.text.errors}: ${totals.errors ?? 0} · ${this.text.averageLatency}:
              ${totals.average_latency_ms ?? 0} ms</span
            >
          </header>
          ${this.renderChart()}
        </section>
        <section class="panel">
          <header class="panel-head"><h2>${this.text.breakdowns}</h2></header>
          ${this.renderBreakdowns()}
        </section>
      </div>
      ${this.renderRecords()}
    </main>`;
  }

  private renderDateForm() {
    return html`<form class="date-form" @submit=${this.applyDates}>
      <label
        >${this.text.from}<input
          type="date"
          name="from"
          .value=${this.from}
          max=${this.to} /></label
      ><label
        >${this.text.to}<input
          type="date"
          name="to"
          .value=${this.to}
          min=${this.from}
          max=${this.isoDaysAgo(0)} /></label
      ><button class="button primary" type="submit">${this.text.refresh}</button>
    </form>`;
  }

  private renderChart() {
    const daily = this.metrics?.daily ?? [];
    const max = Math.max(1, ...daily.map((day) => day.messages));
    return html`<div class="chart" aria-label=${this.text.activity}>
        ${daily.map((day) => {
          const height = Math.max(1, (day.messages / max) * 100);
          return html`<div class="bar-wrap" style="--height:${height}%">
            <span class="tooltip">${day.date} · ${day.messages}</span>
            <div class="bar" style="height:${height}%"></div>
          </div>`;
        })}
      </div>
      <div class="chart-axis">
        <span>${daily.at(0)?.date ?? ''}</span><span>${daily.at(-1)?.date ?? ''}</span>
      </div>`;
  }

  private renderBreakdowns() {
    const breakdowns = this.metrics?.breakdowns ?? {};
    return html`<div class="breakdowns">
      ${['languages', 'models'].map(
        (name) =>
          html`<section class="breakdown">
            <h3>${name === 'languages' ? this.text.language : this.text.model}</h3>
            <div class="rank">
              ${Object.entries(breakdowns[name] ?? {})
                .sort((a, b) => b[1] - a[1])
                .slice(0, 4)
                .map(
                  ([key, value]) =>
                    html`<span title=${this.optionLabel(name, key)}
                        >${this.optionLabel(name, key)}</span
                      ><span class="value">${value}</span>`,
                )}
            </div>
          </section>`,
      )}
    </div>`;
  }

  private renderRecords() {
    return html`<section class="panel">
      <header class="panel-head">
        <h2>${this.text.records}</h2>
        <div class="records-toolbar">
          <div class="tabs" role="tablist">
            ${(['conversations', 'profiles', 'feedback'] as RecordKind[]).map(
              (kind) =>
                html`<button
                  class="tab ${this.kind === kind ? 'active' : ''}"
                  role="tab"
                  aria-selected=${this.kind === kind}
                  @click=${() => this.switchKind(kind)}
                >
                  ${this.text[kind]}
                </button>`,
            )}
          </div>
          <button
            class="button export"
            @click=${this.exportCsv}
            ?disabled=${this.records.length === 0}
          >
            ${this.text.export}
          </button>
        </div>
      </header>
      ${this.kind === 'profiles'
        ? html`${this.renderSurveyStatistics()}
            <p class="note">${this.text.profileNote}</p>`
        : nothing}${this.records.length === 0
        ? html`<div class="empty">${this.text.empty}</div>`
        : html`<div
            class=${this.kind === 'profiles' ? 'profile-table' : ''}
            aria-label=${this.kind === 'profiles' ? this.text.profiles : nothing}
            tabindex=${this.kind === 'profiles' ? '0' : nothing}
          >
            ${this.renderRecordHeader()}
            <div>${this.records.map((record) => this.renderRecord(record))}</div>
          </div>`}${this.nextCursor
        ? html`<div class="load-more">
            <button class="button" @click=${() => this.loadRecords(true)}>
              ${this.text.loadMore}
            </button>
          </div>`
        : nothing}
    </section>`;
  }

  private renderSurveyStatistics() {
    const breakdowns = this.metrics?.breakdowns ?? {};
    const groups = [
      {
        name: 'user_groups',
        title: t('chat.onboarding.form.userGroup.label'),
        options: USER_GROUPS,
      },
      {
        name: 'geodata_experience',
        title: t('chat.onboarding.form.experience.label'),
        options: GEODATA_EXPERIENCE_LEVELS,
      },
      {
        name: 'intended_uses',
        title: t('chat.onboarding.form.intendedUse.label'),
        options: INTENDED_USES,
      },
    ] as const;
    const total = this.metrics?.totals.onboarding ?? 0;
    return html`<section class="survey-statistics" aria-label=${this.text.surveyStatistics}>
      <header class="survey-statistics-head">
        <h3>${this.text.surveyStatistics}</h3>
        <span class="survey-total">${this.formatNumber(total)} ${this.text.responses}</span>
      </header>
      <div class="survey-histograms">
        ${groups.map(({ name, title, options }) =>
          this.renderSurveyHistogram(name, String(title), options, breakdowns[name] ?? {}),
        )}
      </div>
    </section>`;
  }

  private renderSurveyHistogram(
    name: string,
    title: string,
    options: readonly string[],
    counts: Record<string, number>,
  ) {
    const maximum = Math.max(1, ...options.map((option) => counts[option] ?? 0));
    return html`<section class="survey-histogram">
      <h4>${title}</h4>
      <div class="histogram-rows">
        ${options.map((option) => {
          const count = counts[option] ?? 0;
          const width = (count / maximum) * 100;
          return html`<div class="histogram-row">
            <div class="histogram-label">
              <span title=${this.optionLabel(name, option)}>${this.optionLabel(name, option)}</span>
              <span class="histogram-count">${this.formatNumber(count)}</span>
            </div>
            <div class="histogram-track" aria-hidden="true">
              <span class="histogram-bar" style=${`width:${width}%`}></span>
            </div>
          </div>`;
        })}
      </div>
    </section>`;
  }

  private renderRecord(record: AdminRecord) {
    if (this.kind === 'conversations') return this.renderConversationRecord(record);
    if (this.kind === 'profiles') return this.renderProfileRecord(record);
    return html`<button
      class="record-row ${this.selected === record ? 'selected' : ''}"
      aria-label=${this.text.details}
      @click=${() => (this.selected = record)}
    >
      <time>${this.formatDate(record.started_at ?? record.ts ?? record.log_date)}</time
      ><span class="lang">${String(record.lang ?? '—')}</span
      ><span class="record-copy"><strong>${this.recordContent(record)}</strong></span>
    </button>`;
  }

  private renderRecordHeader() {
    if (this.kind === 'profiles')
      return html`<div class="record-header profile-grid" aria-hidden="true">
        <span>${this.text.submitted}</span>
        <span>${this.text.language}</span>
        <span>${this.text.userType}</span>
        <span>${this.text.geodataExperience}</span>
        <span>${this.text.intendedUse}</span>
        <span>${this.text.consent}</span>
      </div>`;
    return html`<div
      class="record-header ${this.kind === 'conversations' ? 'conversation-grid' : ''}"
      aria-hidden="true"
    >
      <span>Date</span><span>Lang.</span><span>${this.recordContentLabel()}</span>${this.kind ===
      'conversations'
        ? html`<span>${this.text.messages}</span>`
        : nothing}
    </div>`;
  }

  private renderProfileRecord(record: AdminRecord) {
    const userType = this.optionLabel('user_groups', String(record.user_group ?? 'unknown'));
    const experience = this.optionLabel(
      'geodata_experience',
      String(record.geodata_experience ?? 'unknown'),
    );
    const intendedUse = this.optionLabel('intended_uses', String(record.intended_use ?? 'unknown'));
    return html`<button
      class="record-row profile-grid profile-record ${this.selected === record ? 'selected' : ''}"
      aria-label=${`${this.text.details}: ${userType}, ${experience}, ${intendedUse}`}
      @click=${() => (this.selected = record)}
    >
      <time>${this.formatDate(record.ts ?? record.log_date)}</time>
      <span class="lang">${String(record.lang ?? '—')}</span>
      <span class="profile-cell" title=${userType}>${userType}</span>
      <span class="profile-cell" title=${experience}>${experience}</span>
      <span class="profile-cell" title=${intendedUse}>${intendedUse}</span>
      <span class="profile-cell profile-consent">${String(record.consent_version ?? '—')}</span>
    </button>`;
  }

  private renderConversationRecord(record: AdminRecord) {
    const conversationId = String(record.conversation_id ?? '');
    const expanded = conversationId === this.expandedConversationId;
    const turns = this.conversationTurns(record);
    const transcriptId = `conversation-${conversationId.replaceAll(/[^a-zA-Z0-9_-]/g, '-')}`;
    return html`<article class="conversation-list-item ${expanded ? 'expanded' : ''}">
      <button
        class="record-row conversation-grid"
        aria-expanded=${expanded}
        aria-controls=${transcriptId}
        @click=${() => this.toggleConversation(conversationId)}
      >
        <time>${this.formatDate(record.started_at ?? record.ts ?? record.log_date)}</time
        ><span class="lang">${String(record.lang ?? '—')}</span
        ><span class="record-copy"><strong>${this.recordContent(record)}</strong></span
        ><span class="conversation-count" aria-label=${`${turns.length} ${this.text.messages}`}>
          <b>${turns.length}</b><span class="disclosure" aria-hidden="true">⌄</span>
        </span>
      </button>
      ${expanded
        ? html`<div
            class="inline-transcript"
            id=${transcriptId}
            role="region"
            aria-label=${this.text.conversationDetails}
          >
            <div class="thread-detail">
              ${this.renderConversationOverview(record, turns)}
              ${this.renderConversationTimeline(turns)}
            </div>
          </div>`
        : nothing}
    </article>`;
  }

  private toggleConversation(conversationId: string) {
    this.expandedConversationId =
      this.expandedConversationId === conversationId ? '' : conversationId;
  }

  private renderDrawer(record: AdminRecord) {
    const turns = this.conversationTurns(record);
    const contentFields = new Set([
      'user_message',
      'assistant_markdown',
      'message',
      'first_user_message',
      'turns',
    ]);
    const metadata = Object.entries(record).filter(
      ([key, value]) => !contentFields.has(key) && key !== 'turn' && value !== undefined,
    );
    return html`<button
        class="scrim"
        aria-label=${this.text.close}
        @click=${this.closeDrawer}
      ></button>
      <aside
        class="drawer"
        aria-label=${this.text.details}
        tabindex="-1"
        @keydown=${this.drawerKeydown}
      >
        <header class="drawer-head">
          <h2>${this.recordSummary(record).title}</h2>
          <button class="icon-button" aria-label=${this.text.close} @click=${this.closeDrawer}>
            ×
          </button>
        </header>
        <div class="drawer-body">
          <section>
            <h3>${this.text.metadata}</h3>
            <dl>
              ${metadata.map(
                ([key, value]) =>
                  html`<dt>${key.replaceAll('_', ' ')}</dt>
                    <dd>${Array.isArray(value) ? value.join(', ') : value}</dd>`,
              )}
            </dl>
          </section>
          ${turns.length > 0
            ? this.renderConversationTimeline(turns)
            : nothing}${record.user_message
            ? html`<section>
                <h3>${this.text.userMessage}</h3>
                <pre class="content-block">${record.user_message}</pre>
              </section>`
            : nothing}${record.assistant_markdown
            ? html`<section>
                <h3>${this.text.answer}</h3>
                <div class="content-block markdown">
                  ${unsafeHTML(renderMarkdown(String(record.assistant_markdown)))}
                </div>
              </section>`
            : nothing}${record.message
            ? html`<section>
                <h3>${this.text.feedbackMessage}</h3>
                <pre class="content-block">${record.message}</pre>
              </section>`
            : nothing}
        </div>
      </aside>`;
  }

  private renderConversationTimeline(turns: AdminRecord[]) {
    return html`<section class="conversation-timeline">
      <h3>${this.text.conversationDetails}</h3>
      ${turns.map(
        (turn, index) =>
          html`<article class="conversation-turn">
            <div class="turn-heading">
              <strong>#${index + 1}</strong><time>${this.formatDate(turn.ts)}</time>
            </div>
            ${this.renderTurnMetadata(turn)}
            <h4>${this.text.userMessage}</h4>
            <pre class="content-block user-block">${String(turn.user_message ?? '—')}</pre>
            ${turn.assistant_markdown
              ? html`<h4>${this.text.answer}</h4>
                  <div class="content-block markdown assistant-block">
                    ${unsafeHTML(renderMarkdown(String(turn.assistant_markdown)))}
                  </div>`
              : nothing}
          </article>`,
      )}
    </section>`;
  }

  private renderConversationOverview(record: AdminRecord, turns: AdminRecord[]) {
    const inputTokens = this.numericValue(record.input_tokens);
    const outputTokens = this.numericValue(record.output_tokens);
    return html`<dl class="thread-overview" aria-label=${this.text.metadata}>
      <div class="wide">
        <dt>${this.text.conversationId}</dt>
        <dd><code>${String(record.conversation_id ?? '—')}</code></dd>
      </div>
      <div>
        <dt>${this.text.started}</dt>
        <dd>${this.formatDate(record.started_at)}</dd>
      </div>
      <div>
        <dt>${this.text.lastActivity}</dt>
        <dd>${this.formatDate(record.updated_at ?? record.started_at)}</dd>
      </div>
      <div>
        <dt>${this.text.messages}</dt>
        <dd>${this.formatNumber(this.numericValue(record.message_count) || turns.length)}</dd>
      </div>
      <div>
        <dt>${this.text.language}</dt>
        <dd>${String(record.lang ?? '—').toUpperCase()}</dd>
      </div>
      <div>
        <dt>${this.text.model}</dt>
        <dd>${this.joinValues(record.models)}</dd>
      </div>
      <div>
        <dt>${this.text.totalLatency}</dt>
        <dd>${this.formatNumber(this.numericValue(record.total_latency_ms))} ms</dd>
      </div>
      <div>
        <dt>${this.text.tokens}</dt>
        <dd>
          ${this.formatNumber(inputTokens)} ${this.text.input} · ${this.formatNumber(outputTokens)}
          ${this.text.output}
        </dd>
      </div>
      <div>
        <dt>${this.text.tools}</dt>
        <dd>${this.joinValues(record.tools_used)}</dd>
      </div>
      <div>
        <dt>${this.text.layers}</dt>
        <dd>${this.formatNumber(this.numericValue(record.layer_count))}</dd>
      </div>
      <div>
        <dt>${this.text.errors}</dt>
        <dd>${this.formatNumber(this.numericValue(record.error_count))}</dd>
      </div>
    </dl>`;
  }

  private renderTurnMetadata(turn: AdminRecord) {
    const inputTokens = this.numericValue(turn.input_tokens);
    const outputTokens = this.numericValue(turn.output_tokens);
    return html`<dl class="turn-metadata" aria-label=${this.text.metadata}>
      <div class="wide">
        <dt>${this.text.messageId}</dt>
        <dd><code>${String(turn.message_id ?? '—')}</code></dd>
      </div>
      <div>
        <dt>${this.text.language}</dt>
        <dd>${String(turn.lang ?? '—').toUpperCase()}</dd>
      </div>
      <div>
        <dt>${this.text.model}</dt>
        <dd>${String(turn.model_id ?? '—')}</dd>
      </div>
      <div>
        <dt>${this.text.latency}</dt>
        <dd>${this.formatNumber(this.numericValue(turn.latency_ms))} ms</dd>
      </div>
      <div>
        <dt>${this.text.tokens}</dt>
        <dd>
          ${this.formatNumber(inputTokens)} ${this.text.input} · ${this.formatNumber(outputTokens)}
          ${this.text.output}
        </dd>
      </div>
      <div>
        <dt>${this.text.tools}</dt>
        <dd>${this.joinValues(turn.tool_calls)}</dd>
      </div>
      <div>
        <dt>${this.text.layers}</dt>
        <dd>${this.formatNumber(this.numericValue(turn.layer_count))}</dd>
      </div>
      ${turn.error_code
        ? html`<div>
            <dt>${this.text.errors}</dt>
            <dd class="error-value">${String(turn.error_code)}</dd>
          </div>`
        : nothing}
    </dl>`;
  }

  private conversationTurns(record: AdminRecord): AdminRecord[] {
    return Array.isArray(record.turns)
      ? record.turns.filter(
          (turn): turn is AdminRecord => typeof turn === 'object' && turn !== null,
        )
      : [];
  }

  private recordSummary(record: AdminRecord) {
    if (this.kind === 'profiles')
      return {
        title: this.optionLabel('user_groups', String(record.user_group ?? 'unknown')),
        subtitle: `${this.optionLabel('geodata_experience', String(record.geodata_experience ?? 'unknown'))} · ${this.optionLabel('intended_uses', String(record.intended_use ?? 'unknown'))}`,
      };
    if (this.kind === 'feedback')
      return {
        title: String(record.category ?? this.text.feedback),
        subtitle: this.shorten(String(record.message ?? ''), 110),
      };
    return {
      title: this.shorten(
        String(record.first_user_message ?? record.user_message ?? 'Conversation'),
        110,
      ),
      subtitle: record.error_code
        ? `${this.text.errors}: ${record.error_code}`
        : `${Array.isArray(record.tool_calls) ? record.tool_calls.length : 0} tools · ${record.latency_ms ?? 0} ms`,
    };
  }

  private recordContentLabel() {
    if (this.kind === 'profiles') return this.text.profiles;
    if (this.kind === 'feedback') return this.text.feedbackMessage;
    return this.text.userMessage;
  }

  private recordContent(record: AdminRecord) {
    if (this.kind === 'profiles') {
      const summary = this.recordSummary(record);
      return `${summary.title} · ${summary.subtitle}`;
    }
    if (this.kind === 'feedback') return String(record.message ?? '—');
    return String(record.first_user_message ?? record.user_message ?? '—');
  }

  private async applyDates(event: SubmitEvent) {
    event.preventDefault();
    const form = new FormData(event.currentTarget as HTMLFormElement);
    this.from = String(form.get('from'));
    this.to = String(form.get('to'));
    this.selected = undefined;
    this.expandedConversationId = '';
    await this.loadAll();
  }
  private async loadAll() {
    this.loading = true;
    this.failed = false;
    try {
      const query = `?from=${encodeURIComponent(this.from)}&to=${encodeURIComponent(this.to)}`;
      const [response] = await Promise.all([
        adminFetch(`/metrics${query}`),
        this.loadRecords(false),
      ]);
      if (response.status === 401) {
        this.authenticated = false;
        return;
      }
      if (!response.ok) throw new Error();
      this.metrics = (await response.json()) as AdminMetrics;
    } catch {
      this.failed = true;
    } finally {
      this.loading = false;
    }
  }
  private async loadRecords(append: boolean) {
    const cursor =
      append && this.nextCursor ? `&cursor=${encodeURIComponent(this.nextCursor)}` : '';
    const response = await adminFetch(
      `/records/${this.kind}?from=${this.from}&to=${this.to}&limit=50${cursor}`,
    );
    if (!response.ok) throw new Error();
    const page = (await response.json()) as RecordPage;
    this.records = append ? [...this.records, ...page.items] : page.items;
    this.nextCursor = page.next_cursor;
  }
  private async switchKind(kind: RecordKind) {
    this.kind = kind;
    this.selected = undefined;
    this.expandedConversationId = '';
    this.records = [];
    this.nextCursor = null;
    try {
      await this.loadRecords(false);
    } catch {
      this.failed = true;
    }
  }
  private closeDrawer() {
    this.selected = undefined;
  }
  private drawerKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') this.closeDrawer();
  }
  private async submitAuthentication(event: SubmitEvent) {
    event.preventDefault();
    const data = new FormData(event.currentTarget as HTMLFormElement);
    this.authError = '';
    this.authSubmitting = true;
    try {
      const email = String(data.get('email') ?? '')
        .trim()
        .toLowerCase();
      await signIn(email, String(data.get('password') ?? ''));
      this.authenticated = true;
      await this.loadAll();
    } catch {
      this.authError = this.text.authError;
    } finally {
      this.authSubmitting = false;
    }
  }
  private async signOut() {
    await logout();
    this.authenticated = false;
    this.authError = '';
  }
  private async setLanguage(event: Event) {
    await changeLanguage((event.target as HTMLSelectElement).value as AppLanguage);
    this.requestUpdate();
  }
  private isoDaysAgo(days: number) {
    const value = new Date();
    value.setUTCDate(value.getUTCDate() - days);
    return value.toISOString().slice(0, 10);
  }
  private formatDate(value: unknown) {
    if (!value) return '—';
    const date = new Date(String(value));
    return Number.isNaN(date.valueOf())
      ? String(value)
      : new Intl.DateTimeFormat(currentLanguage(), {
          dateStyle: 'medium',
          timeStyle: 'short',
        }).format(date);
  }
  private numericValue(value: unknown) {
    return typeof value === 'number' && Number.isFinite(value) ? value : 0;
  }
  private formatNumber(value: number) {
    return new Intl.NumberFormat(currentLanguage()).format(value);
  }
  private joinValues(value: unknown) {
    if (!Array.isArray(value)) return value ? String(value) : '—';
    const values = value.filter((item): item is string => typeof item === 'string' && item !== '');
    return values.length > 0 ? values.join(', ') : '—';
  }
  private shorten(value: string, length: number) {
    return value.length > length ? `${value.slice(0, length - 1)}…` : value;
  }
  private optionLabel(group: string, key: string) {
    const section: Record<string, string> = {
      user_groups: 'userGroup',
      geodata_experience: 'experience',
      intended_uses: 'intendedUse',
    };
    return section[group]
      ? t(`chat.onboarding.form.${section[group]}.options.${key}`, {
          defaultValue: key.replaceAll('_', ' '),
        })
      : key;
  }
  private exportCsv() {
    const keys = [...new Set(this.records.flatMap((record) => Object.keys(record)))];
    const quote = (value: unknown) => {
      const serialized = typeof value === 'object' ? JSON.stringify(value) : String(value ?? '');
      return `"${serialized.replaceAll('"', '""')}"`;
    };
    const csv = [
      keys.map(quote).join(','),
      ...this.records.map((record) => keys.map((key) => quote(record[key])).join(',')),
    ].join('\n');
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    link.download = `sgs-${this.kind}-${this.from}-${this.to}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-admin-app': SgsAdminApp;
  }
}
