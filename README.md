# SGS LLM

Conversational chat and web map application for Swiss federal geodata.

## Description

SGS LLM is an open-source prototype for making Swiss federal geodata accessible to
non-experts through natural language. The application combines a conversational interface,
an interactive web map, Swisstopo API connectors, and LLM-based orchestration so users can
discover, query, and visualize official geodata without needing GIS expertise.

The project is developed in the context of the Swiss Geoinformation Strategy (SGS). It
continues prior SGS work on large language models and geodata, and explores how
conversational access, MCP-compatible connectors, and agent-based workflows can support
future Swiss geodata services.

The prototype is hosted on Swisstopo's GitHub organization and is intended to run on
Swisstopo infrastructure.

## Disclaimer

This repository has been initialized for the 2026 prototype.

The first implementation work will add the application scaffold, development setup,
connector modules, test framework, and deployment documentation. Until then, this README
describes the project purpose and planned structure rather than a runnable application.

All contents of this repository are subject to change during the prototype phase, including
the architecture, interfaces, module boundaries, repository layout, development commands,
and deployment approach.

## Planned capabilities

- Conversational interface for natural language questions about Swiss geodata
- Interactive map for displaying layers, query results, and spatial context
- Dataset and layer discovery across Swisstopo geodata services
- Swisstopo API connectors for search, access, and filtering operations
- MCP-compatible tool definitions for use by LLM agents
- Multilingual interaction patterns for Swiss public-sector use cases
- Test framework for end-to-end, component, and multilingual evaluation
- Deployment documentation for Swisstopo-managed infrastructure

## Architecture overview

The prototype is planned as a chat and map application backed by an agent integration layer
and Swisstopo API connectors.

```text
User
  |
  v
Chat + web map frontend
  |
  v
LLM / agent integration
  |
  v
Swisstopo connector layer
  |
  v
Swisstopo geodata services
```

The connector layer is expected to expose search, access, and filtering capabilities to the
LLM integration layer. The application should keep official geodata in Swisstopo source
systems and access data through supported APIs.

## Getting started

Clone the repository:

```bash
git clone https://github.com/swisstopo/sgs-llm.git
cd sgs-llm
```

## Usage

Run the bundled mock agent (simulates the agent backend, terminal 1):

```bash
cd mock-agent
npm install
npm start          # WebSocket on ws://localhost:8787/ws/v1
```

Run the frontend in development mode (terminal 2):

```bash
cd frontend
npm install
npm run dev
```

The chat speaks the WebSocket protocol documented in
[docs/protocol.md](docs/protocol.md); the agent endpoint is configured via
`frontend/public/config.json`.

Other frontend commands:

```bash
npm run build   # type-check and create a production build in dist/
npm test        # run the unit tests (vitest)
npm run lint    # run eslint
```

## Support

Use the established Swisstopo SGS LLM project channels for support and coordination.

## Authors & acknowledgements

This project is developed for Swisstopo with contributions from:

- [Ageospatial Sàrl](https://www.ageospatial.com) - frontend, web map, Swisstopo API
  connectors, and MCP-compatible connector design
- [askEarth AG](https://ask.earth) - LLM provisioning, agent integration, MCP client
  integration, and testing framework

The work is financed in the context of the Swiss Geoinformation Strategy (SGS).

## License

See [LICENSE](LICENSE).

## Related projects

- [`swisstopo/sgs-llm-module`](https://github.com/swisstopo/sgs-llm-module) -
  companion module repository for the SGS LLM prototype.
