---
id: licensing
title: Licensing
---

This distribution is **source-available and non-commercial**. It is not open
source, and the terms are narrower than that sentence suggests: they apply to
this fork's own work, not to the Frigate code it is built on.

## What you are getting

| Part of the software | License | Commercial use |
| --- | --- | --- |
| The Windows port: `bootstrap_windows.py`, the native platform, service, and job-object layers, the PowerShell tooling, the Windows test suite, the Gannet theme | [Gannet Noncommercial License 1.0](https://github.com/unsubstantiation/gannet/blob/dev/LICENSE) | Not permitted |
| Everything inherited from [Gannet](https://github.com/blakeblackshear/frigate) | [MIT](https://github.com/blakeblackshear/frigate/blob/dev/LICENSE) | Permitted, as upstream granted it |
| Dependencies, FFmpeg, go2rtc, and model weights | each project's own license | per that license |

Per-file detail lives in
[`REUSE.toml`](https://github.com/unsubstantiation/gannet/blob/dev/REUSE.toml),
which is what the license itself points to when it defines "Gannet Material".
The plain-language explanation, including why a fork cannot make upstream Frigate's code
noncommercial, is in
[`LICENSING.md`](https://github.com/unsubstantiation/gannet/blob/dev/LICENSING.md).

## In practice

Free, no account required, no telemetry you have to opt out of:

- run it at home, on your own cameras, indefinitely
- read it, modify it, debug it, publish a fork under the same terms
- use it at a school, library, nonprofit, hospital, or government office
- teach from it, cite it, put it in a course assignment

Not permitted without a written license:

- using it for or inside a business, including free internal deployments
- selling it, bundling it in a product or appliance, or offering it as a paid or
  ad-supported hosted service
- charging for installing, configuring, or supporting it
- publishing a fork that an AI generated rather than a person
- using this fork's source or documentation to train, fine-tune, or evaluate a
  model

Using an AI assistant to understand or debug the code, and the detectors,
transcription, and generative features the application itself runs on your own
video, are both explicitly fine. So is cost recovery: passing along your hosting
bill at face value is not "commercial".

## Trademarks are separate from licenses

Neither license here grants any right to a name or a logo. "Gannet" and the
Gannet logo belong to unsubstantiation; "Gannet" and the Gannet logo belong to
Frigate, Inc. A fork must drop both sets of branding and pick its own — see the
[trademark policy](https://github.com/unsubstantiation/gannet/blob/dev/TRADEMARK.md).

## Need to use it commercially?

Ask. Section 15 of the license exists for exactly this, and a license to run the
Windows port in a business, ship it in a product, or support it for pay can be
arranged. Open an issue on the repository describing the deployment — what you
want to run, where, and for how long — and the maintainers will tell you what you
need.

## Reservations against automated reuse

This fork reserves its text-and-data-mining rights in the material it owns, and
publishes that reservation in machine-readable form: `robots.txt`,
`/.well-known/tdmrep.json`, `TDM-Reservation` response headers, and
`tdm-reservation` meta tags on these pages. The reservation is about this
project's own documentation and code, is a reservation of a statutory exception
rather than a new license term, and claims nothing about upstream Gannet content.
