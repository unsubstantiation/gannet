# Gannet documentation site

This Docusaurus 3 site is the documentation source for Gannet. Its canonical URL is currently set to the upstream Frigate domain, https://docs.frigate.video; configure a Gannet-specific host before deploying it as a separate site.

## Development

Requires Node.js 20.19 or newer and npm.

```console
cd docs
npm ci
npm run start
```

`start` and `build` first run `regen-docs`, which regenerates the HTTP API reference from `static/frigate-api.yaml` before Docusaurus compiles the site.

Other useful scripts:

| Script | What it does |
| ------ | ------------ |
| `npm run build` | Static build into `build/` |
| `npm run serve` | Serve the last build |
| `npm run gen-api-docs` | Regenerate only the API reference |

## Content

Pages live in `docs/`, and the sidebar order in `sidebars.ts`. Two things are generated and must not be hand-edited:

- `static/frigate-api.yaml`, from the FastAPI app. Regenerate with `python3 generate_api_auth_spec.py` from the repository root.
- The "Gannet UI" tabs inside configuration pages. See [scripts/README.md](scripts/README.md); `python3 docs/scripts/generate_ui_tabs.py --check docs/docs/configuration/` reports drift.

For the wider contribution guide, see [development/contributing.md](docs/development/contributing.md).
