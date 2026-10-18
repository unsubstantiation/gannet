## Gannet Documentation Brand Assets

This directory holds the logo mark and favicon used by the Gannet documentation
site, and they belong to **unsubstantiation** (fairuniversal.com), the individual
who maintains this fork. These images are brand material, not software: they are **not** licensed by
the MIT license that covers upstream Frigate code, nor by the noncommercial license
that covers this fork's own code. Names and logos travel under trademark law, and
neither license moves them.

### You may

- display these assets to identify this fork and its documentation, and
- link to them.

### You may not

- use them in a way that suggests this fork, its author, or its documentation
  endorse or sponsor your project,
- present them as your own, or register them (or anything confusingly similar) as a
  trademark, service mark, or other source indicator, or
- ship them inside your own modified version of this software.

### If you fork or otherwise modify this software, replace these assets

Distribute a modified version and you must use your own name and your own images
here — editing these files is not enough, because the point is that the artwork
identifies *us*. Delete what is in this directory, put your own equivalent files at
the same paths, and update `docs/docusaurus.config.ts` (`favicon`, `navbar.logo`) to
match. Saying accurately, in plain text, that your version is derived from Gannet is
always fine.

### What changed here

Frigate's documentation assets — `frigate.png`, `logo.svg`, `logo-dark.svg`, and its
`favicon.ico` — were **removed** from this fork rather than licensed, so nothing in
this directory is Frigate, Inc. property any more. That removal is what
`docs/docusaurus.config.ts` and this fork's `TRADEMARK.md` both require of a fork
that ships a modified version; the upstream attribution for the surrounding
documentation lives in `LICENSES/MIT.txt` at the repository root and is untouched.
