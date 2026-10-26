# Licensing

**This project is source-available and non-commercial. It is not open source.**
Everything below explains what that means here, what it does not mean, and where
the boundary of it runs. The operative texts are [`LICENSE`](LICENSE) and
[`LICENSES/MIT.txt`](LICENSES/MIT.txt); the file-by-file mapping is
[`REUSE.toml`](REUSE.toml).

## The short version

| You want to… | Then |
| --- | --- |
| Run this at home, on your own cameras, forever | Yes. Free, no account, no phone home, no fee. |
| Read it, study it, debug it, patch it for yourself | Yes. |
| Send a pull request, write a plugin, publish a hobby fork | Yes, under the same terms. |
| Use it at a school, library, charity, fire department, lab, or government office | Yes — named as a permitted purpose in `LICENSE` §4.3. |
| Teach a course from it, or cite it in a paper | Yes. |
| Sell it, bundle it in a paid product, ship it in an appliance or a hosted service, or charge for installing it | No. Not without a written license from unsubstantiation (`LICENSE` §5, §15). |
| Let your company run it on company cameras, for free, internally | No. Free-of-charge is not the test; business use is (`LICENSE` §5.1 a, f). |
| Build a fork with an LLM and publish it | No (`LICENSE` §8.2). |
| Feed the source into a model to train or fine-tune on | No (`LICENSE` §8.1). |
| Ask an AI tool to explain an error, or let Copilot help you patch your copy | Yes (`LICENSE` §8.3). |
| Use the parts of this repository that are Frigate's own code | Yes, under MIT, commercially included — see "The boundary". |
| Say this is "open source" | Please don't. It isn't, and the label is someone else's certification mark. |

## The boundary, honestly

This repository is a fork of [Frigate](https://github.com/blakeblackshear/frigate),
which is MIT-licensed. A fork cannot take rights away from the people upstream
granted them, so the noncommercial terms here are deliberately narrow:

| What | Terms | Where to verify |
| --- | --- | --- |
| Files not assigned a more-specific annotation (default `**`) | **MIT** — commercial use allowed; this fork does not narrow the upstream grant | `REUSE.toml` |
| Upstream-derived files explicitly listed as changed by Gannet | **MIT AND LicenseRef-GNCL-1.0** — upstream portions stay MIT; Gannet-authored changes carry these terms | `REUSE.toml` |
| Files explicitly identified as Gannet Material | **LicenseRef-GNCL-1.0** — non-commercial, share-alike, no-ML-training | `REUSE.toml` and the file notices |
| Third-party catalogs, lockfiles, binaries, brand assets, and dependencies | Their respective licenses; we claim no additional rights | The files' notices and [`THIRD_PARTY.md`](THIRD_PARTY.md) |

Two guards on the third row, because a fork that insists on honesty from its
users has to start with honesty about its own claims:

- **A new file is not automatically original.** The generator screens
  fork-only files against the upstream tree for copied lines and demotes
  anything above a quarter of the file to `MIT AND LicenseRef-GNCL-1.0`. Both
  `web/themes/*.css` tripped it and are dual-licensed for that reason.
  `python scripts/generate_reuse_toml.py --report` prints the files nearest the
  line, for a person to read.
- **Two paths are never claimed, whatever the heuristic says.**
  `LICENSES/MIT.txt` is Frigate's own license text sitting at a path upstream
  does not have, and `scripts/license_audit_cache.json` is generated. Claiming
  the first would be the exact abuse this layout is meant to prevent.

`REUSE.toml` is the authoritative list: generated against
`frigate-dev@ee2ae1a` on 18 October 2026, never hand-edited, and regenerated
after every upstream merge with `scripts/generate_reuse_toml.py`. Anything the
mapping does not claim falls back to MIT, never to us. `gannet/test/test_licensing.py`
fails if the license files, the mapping, and the READMEs drift apart.

**What follows from that, stated plainly:** anyone may take the Frigate-authored
majority of this tree, commercially, from us or from upstream, under MIT. What
they may not do is commercialize the Windows port work specifically — the
bootstrap, the native service integration, the platform layer, the packaging. If
you were hoping this license would stop commercial forks of Frigate itself, it
does not and cannot; only Frigate, Inc. can change those terms. We chose a real
boundary we can defend over a bold claim we could not.

## Why "non-commercial open source" was not an option

The Open Source Definition forbids exactly the restriction that was wanted here.
Criterion 6, *No Discrimination Against Fields of Endeavor*, says a license "must
not restrict anyone from making use of a program in a specific field of endeavor"
and notes that it "may not restrict the program from being used in a business";
criterion 5 forbids excluding persons or groups. The FSF's freedom 0 and the
DFSG say the same thing. OSI's own guidance adds that a project may publish such
a license, but may not call it open source or use the OSI marks.

So the two requirements are contradictory, and the resolution had to drop one.
This project dropped the label and kept the restriction, because a restriction
that is enforceable does the work the label was meant to do. If you are weighing
the same choice, the honest menu is short:

| You want | Closest real option | What it costs |
| --- | --- | --- |
| No closed-source commercial forks, but keep the open-source label | AGPL-3.0-only | A business may still run it, resell it, and charge for support — it just has to publish its changes. Copyleft polices distribution, not use. |
| No commercial use at all | PolyForm Noncommercial 1.0.0, or ours | The label, distro acceptance, and most package-manager policies. |
| No commercial use *and* the label | nothing exists | Not a drafting failure. OSD criteria 5 and 6 are what stand in the way, and every project that has tried has had to drop one. |

`LICENSE` is built on the second row's license. See "Where this text came from".

## Where this text came from

`LICENSE` is a modified version of the **PolyForm Noncommercial License 1.0.0**
([polyformproject.org/licenses/noncommercial/1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)),
whose own repository grants
[permissive reuse of the license text](https://github.com/polyformproject/polyform-licenses). Everything unmentioned is PolyForm's
own text, kept as written: acceptance, the grant structure, the noncommercial and
personal-use sections, fair use, the patent grant and patent defense, violations,
and no-liability. What this fork added is the ownership carve-outs in §1, the
business-use and cost-recovery definitions in §5, the share-alike and source-form
terms in §7, all of §8, §12.1's TDM reservation, the survival clause in §14.2, and
the definitions in §17.

PolyForm's own rule is that a modified license must drop the PolyForm name and
URL from the license text, which is why `LICENSE` never mentions them and this
file does. That is also why the identifier is `LicenseRef-GNCL-1.0` — a custom
SPDX id — rather than `PolyForm-Noncommercial-1.0.0`: this is *not* the standard
text, and nobody should scan it, rely on its SPDX metadata, or assume its
behavior is PolyForm's. If you want the standard terms for your own project, take
them from PolyForm unmodified; they are better than anything you will draft, and
they do not need a `LICENSING.md` to explain themselves.

## Machine-readable AI and mining reservations

`LICENSE` §8 is a contract with people who accept it. These files are signals for
systems that never read it, and they cover only what this fork owns (our
documentation and brand assets, not Frigate's code):

| File | Purpose |
| --- | --- |
| `docs/static/robots.txt` | `User-agent: *` `Disallow:` plus the Content-Signal form (`ai-train: no`) that AI crawlers parse, and named blocks for known training and retrieval crawlers |
| `docs/static/.well-known/tdmrep.json` | W3C TDMRep reservation, `tdm-reservation: 1`, with a `tdm-policy` pointer to this file |
| `docs/docusaurus.config.ts` | `tdm-reservation: 1` and `tdm-policy` meta tags on every docs page, plus `noai, noimageai` in the robots tag |
| `docs/static/_headers` | the same reservation as an HTTP response header, for hosts that read headers rather than bodies |

Why this is worth doing in 2026 rather than being decorative: under Article 4(3)
of Directive (EU) 2019/790 an express, machine-readable reservation removes the
text-and-data-mining exception, and Article 53(1)(c) of the AI Act — applicable
since 2 August 2026, with the GPAI Code of Practice's copyright chapter alongside
it — requires providers of general-purpose models to identify and respect such
reservations, wherever the training happens. It does not fix everything: US law
on training is unsettled, no signal stops a developer pasting a file into a chat
window, and §8.3 keeps that conduct lawful for you anyway.

## Contributor terms

There is no CLA and no assignment; you keep your copyright.

- Your contribution arrives under these terms — `LicenseRef-GNCL-1.0` for new
  Gannet Material, MIT for changes to upstream files, both for the mixed ones.
  Inbound equals outbound.
- Changes to upstream files must not *add* restrictions to the MIT parts, so a PR
  that relabels a Frigate file as Gannet Material will be closed.
- You may keep licensing your own contribution under MIT or Apache-2.0 as well,
  in parallel, and say so in the PR. Dual-granting is welcome; it does not
  weaken these terms for everyone else.
- Contributors before 18 October 2026 contributed under MIT. That grant stands, so
  material they wrote may be used under MIT where it can be separated out; if you
  are one of them and want your code brought under `LicenseRef-GNCL-1.0` too,
  open an issue and we will do it with your written agreement.

## If you want a commercial license

`LICENSE` §15 exists for this. A business that wants to run the Windows port on
company cameras, resell it, bundle it, or support it for pay should open an issue
or write to the maintainers. Anything from a small per-deployment fee to a
free license for a specific class of user is on the table; the point of the
non-commercial license is that the party who wants to make money off this work
has to ask, not that they cannot.

## Things this fork still owes

Not licensing questions, but they sit next to them and are easy to forget:

- **Names inside the code.** Branding is done where users meet it: Frigate's logo,
  wordmark, and docs favicon are deleted from the tree, the READMEs and the docs
  site carry Gannet's own art and name, and the winget manifest is
  `unsubstantiation.GannetNVR` instead of Frigate's identifier. What remains is
  internal and load-bearing: the package directory is `gannet/`,
  `pyproject.toml` still builds a `frigate-nvr` distribution (which
  `gannet/util/version.py` looks up to resolve the running version), config keys
  and environment variables still use the `FRIGATE_` prefix, the default data
  directory is still `%LOCALAPPDATA%\Frigate`. Compatibility-facing runtime names,
  configuration and environment variables, MQTT/API identifiers, and parts of the
  inherited UI and startup output still refer to Frigate. Changing those interfaces
  needs an explicit migration plan to protect existing installs. Repository prose and
  visible product branding now use Gannet where appropriate; remaining references
  identify upstream, preserve compatibility, or remain in inherited UI/runtime text.
- **The docs host.** `docs/docusaurus.config.ts` still sets `url` to
  `docs.frigate.video` (flagged with `FIXME(owner)` in the file), so the generated
  canonical links and the sitemap advertise upstream's domain, and `netlify.toml`
  deploys to whatever it is currently configured for. Terms published on somebody
  else's domain are a poor look for a project that licenses commercial use by hand:
  repoint the site, or keep the licensing terms in the repository only.
- **A lawyer.** This is drafted license text, not legal advice. Before the first
  enforcement letter or the first paid commercial license, have counsel in the
  jurisdiction you intend to use read Sections 5, 7, and 8 of `LICENSE`.

## If you disagree with this change

Then do not use the Gannet Material. Use Frigate, use the Frigate-authored parts
of this repository under MIT, or fork the tree at the last commit before 18
October 2026 — all of that is lawful, permitted, and unsurprising, and the
version of this project's history before that date is permanently MIT.
