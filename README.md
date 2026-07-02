# Amyris Hermes

Hermes is a monorepo for the web dashboard, Convex control plane, Eve agent, fleet controller, lab skeleton, and Photon sidecar.

## Quick start

From a fresh clone:

```bash
npm run setup
npm run dev
```

`npm run setup` installs the Node apps and Python development tools. `npm run dev` starts the web dashboard. Run app-specific services from their directories when you need Convex, the fleet controller, or the lab skeleton.

## Repository map

| Path                  | Purpose                                              |
| --------------------- | ---------------------------------------------------- |
| `web/`                | Next.js dashboard and Playwright end-to-end tests    |
| `control-plane/`      | Convex HTTP routes, schema, queue, and billing logic |
| `agent/`              | Eve-based agent runtime                              |
| `fleet/controller/`   | Python controller for tenant containers              |
| `lab/skeleton/`       | FastAPI webhook bridge and regression harness        |
| `lab/photon-sidecar/` | Node sidecar for Photon Spectrum messaging           |

## Quality gates

Run the full local readiness gate before handing changes to another agent or reviewer:

```bash
npm run check
```

Useful focused checks:

```bash
npm run lint
npm run format:check
npm run typecheck
npm run test:unit
npm run test:coverage
npm run quality
```

The root tooling enforces ESLint naming, complexity, unused import, and module-boundary rules for JavaScript and TypeScript. Python code is checked with Ruff, Black, strict mypy, pytest duration reporting, and coverage thresholds. Duplicate code, dependency drift, unused dependencies, tracked TODOs, and large files are checked by the root quality scripts.

## Agent workflow

Read `AGENTS.md` before changing code. It includes the GitNexus impact-analysis rules agents must follow, including `gitnexus_impact` before symbol edits and `gitnexus_detect_changes` before commits.

## API schema

The Convex HTTP API schema is generated at `docs/api/hermes-control-plane.openapi.yaml`.

```bash
npm run docs:generate
npm run docs:check
```
