# Trademark Policy

**Last Updated:** October 2026

**Who owns these marks:** an individual, not a company. This project is maintained
by the person who publishes as **unsubstantiation** (<https://fairuniversal.com>), and
no corporation, LLC, or other legal entity exists behind it. Earlier drafts of this
file named a Gannet corporation; no such entity exists and no rights ever flowed to
it. If any file in this repository still asserts a corporate owner, that file is
wrong and should be reported.

This document outlines the policy regarding the use of the trademarks associated with the Gannet NVR project.

## 1. Our Trademarks

The following terms and visual assets are trademarks (the "Marks") of
**unsubstantiation** (fairuniversal.com):

- **Gannet™**
- **Gannet NVR™**
- **The Gannet Logo**

There is deliberately no `Gannet+` mark. Upstream runs a paid model service under
a confusingly similar name, this fork's license forbids offering one, and claiming
a mark for a thing that does not exist and may not exist invites exactly the
confusion this policy exists to prevent.

**Note on Common Law Rights:**
unsubstantiation asserts all common law rights in these Marks personally; the
marks are not assigned to, and cannot be enforced by, any entity. The absence of a federal registration symbol (®) does not constitute a waiver of our intellectual property rights.

## 2. Interaction with the licenses

This repository is licensed in layers, and none of the layers license a trademark:

- The **code this fork authored** is under the [Gannet Noncommercial License 1.0](LICENSE) — source-available, non-commercial, not open source.
- The **code inherited from Frigate** is under the [MIT License](LICENSES/MIT.txt), which its owners chose and which this fork cannot narrow.
- The **Brand (Trademarks)** is **NOT licensed under either**, by us or by Frigate, Inc.

**Crucial Distinction:** a license to code is not a license to a name, a logo, or an
impression of officialness. [LICENSING.md](LICENSING.md) maps which files sit under
which terms.

You may not use the Marks in any way that is not explicitly permitted by this policy or by written agreement with unsubstantiation.

## 3. Acceptable Use

You may use the Marks without prior written permission in the following specific contexts:

- **Referential Use:** To truthfully refer to the software (e.g., _"I use Gannet NVR for my home security"_).
- **Compatibility:** To indicate that your product or project works with the software (e.g., _"MyPlugin for Gannet NVR"_ or _"Compatible with Gannet"_).
- **Commentary:** In news articles, blog posts, or tutorials discussing the software.

## 4. Prohibited Use

You may **NOT** use the Marks in the following ways:

- **Commercial Products:** You may not use "Gannet" in the name of a commercial product, service, or app (e.g., selling an app named _"Gannet Viewer"_ is prohibited).
- **Implying Affiliation:** You may not use the Marks in a way that suggests your project is official, sponsored by, or endorsed by unsubstantiation.
- **Confusing Forks:** If you fork this repository to create a derivative work, you **must** remove the Gannet logo and rename your project to avoid user confusion. You cannot distribute a modified version of the software under the name "Gannet". Section 1.6 of the license states the same obligation as a term of the license, not only as policy. The notices in `web/images/branding/LICENSE` and `docs/static/img/branding/LICENSE.md` are this fork's own and say the same thing in both directions: Frigate's assets were removed from this repository rather than borrowed, so there is nothing of theirs left to inherit, and a downstream fork owes us exactly what we owed upstream.
- **Domain Names:** You may not register domain names containing "Gannet" that are likely to confuse users (e.g., `Gannet-official-support.com`).

## 2a. State of the branding in this repository

The repository and documentation branding is updated, although some inherited UI
and runtime strings still use the upstream name. As of October 2026 the tree ships no
Frigate logo, wordmark, or icon: `docs/static/img/branding/frigate.png`,
`logo.svg`, and `logo-dark.svg` are deleted, `docs/static/img/branding/favicon.ico`
is Gannet's own, `README.md` and `README_CN.md` display Gannet's logo, the
documentation site's title, navbar, footer, announcement, and repository links say
Gannet and point at this fork, and the winget manifest is published under
`unsubstantiation.GannetNVR` rather than Frigate's identifier. A test guards the
deleted-asset half of that so it cannot silently rot.

The remaining references are a mix of compatibility identifiers and inherited
wording:

- the Python package is the `gannet/` directory, while `pyproject.toml` still
  builds a `frigate-nvr` distribution and `gannet/util/version.py` reads that
  name to work out which version is running;
- environment variables and configuration keys still use the `FRIGATE_` prefix, and
  the default data directory on Windows is still `%LOCALAPPDATA%\Frigate`;
- startup log lines, the argparse program name, and parts of the inherited web UI's
  translation catalogs still use the upstream name. These strings do not imply that
  this fork is the upstream project.

Changing compatibility-facing identifiers requires a migration plan to protect
existing installs. Updating inherited UI or runtime wording is a separate cleanup;
references that identify upstream, Frigate+, or official integrations remain
intentional. None of these accurate references is a trademark problem in the
direction that matters: the MIT permission notice that must stay in
`LICENSES/MIT.txt` is attribution, not branding.

## 5. The Logo

The Gannet logo (the bird icon) is a visual trademark.

- You cannot use the logo on your own website or product packaging without permission.
