# OS-APS Typesetting

A [Janeway](https://github.com/BirkbeckCTP/janeway) workflow plugin that replaces
the built-in Typesetting stage with one built around the
[Open Source Academic Publishing Suite](https://os-aps.de) (OS-APS / SciFlow).

OS-APS is a self-hostable Node.js application that converts DOCX to semantic
HTML and exports PDF, HTML, JATS XML and EPUB, with a WYSIWYG editor for
correcting the conversion first.

## What it does

The plugin adds an `osaps_typesetting` stage to a journal's editorial workflow:

- An editor opens an article in the stage and, optionally, assigns a typesetter.
  Assignment is optional throughout — many journals have no dedicated
  typesetter, and an editor can do the work themselves.
- The typesetter gets a task page listing the files to take into OS-APS, a link
  to the journal's configured OS-APS instance, and an upload form.
- Exported PDF or HTML files are uploaded back as Janeway galleys. HTML exports
  reference their images by absolute URL on the OS-APS server; the plugin
  rewrites those to local filenames so the published article does not hotlink
  figures from an OS-APS instance.
- The editor reviews the galleys and completes the stage, which advances the
  article to the next workflow element.

This is **Phase 1: manual handoff.** Files move between Janeway and OS-APS by
hand. Two later phases are designed for but not built: embedding the SciFlow
editor in an iframe, and full API integration. `SPEC.md` records the design and
what each phase is meant to add; `OSAPSAssignment.osaps_project_url` is the
field Phase 3 will use.

## Requirements

- Janeway 1.8 or later (developed against Janeway 1.8, Django 4.2, Python 3.10)
- An OS-APS instance — the public demo at <https://os-aps.sciflow.net/start> or
  your own

## Installation

Clone into your Janeway install's plugin directory. The directory name is the
Django app label and must match exactly:

```bash
git clone https://github.com/justingonder/janeway-osaps-typesetting.git \
    src/plugins/osaps_typesetting
```

Then, from the Janeway repository root:

```bash
python src/manage.py migrate
python src/manage.py install_plugins osaps_typesetting
```

**Restart the server.** Janeway registers plugins once per process, at startup:
a server that was running before the plugin was installed has no URLs and no
workflow registration for it, and Django's autoreloader will not pick up a
brand-new package.

Finally, add **OS-APS Typesetting** to the journal's workflow under
Manager → Workflow. It is designed to take the place of the built-in Typesetting
element rather than sit alongside it.

## Configuration

One journal-level setting, editable by editors and journal managers at
Manager → Plugins → OS-APS Typesetting:

| Setting | Default |
|---|---|
| `osaps_instance_url` | `https://os-aps.sciflow.net/start` |

This is the OS-APS instance typesetters are sent to from their task page. Point
it at your own instance if you self-host.

## Tests

```bash
python src/manage.py test plugins.osaps_typesetting.tests
```

90 tests covering models, logic, the security decorators, every view, the
template tags and the dashboard element.

Note the module path: `src/plugins/` has no `__init__.py`, so the shorter
`test plugins.osaps_typesetting` label makes unittest's directory discovery fail
on a namespace package.

`test_urls.py` exists only for the tests. Plugin URLs are not registered under
the test runner, because Janeway mounts a plugin's URLs only if an enabled
`Plugin` row exists when the URLconf is imported, and the test database is
created empty. See that module's docstring.

## Project files

- `SPEC.md` — the architecture and design decisions, including the three-phase
  roadmap
- `HANDOFFS.md` — what was learned building it: Janeway's landmines, where the
  implementation deviates from the spec and why, and the open questions

## Status

Phase 1 is complete and tested against a local Janeway install. It has not yet
been through California Digital Library's two-developer review, and has not been
run in production.

Known gaps, all deliberate for Phase 1 and listed in `HANDOFFS.md`: no email
notifications when a typesetter is assigned or finishes, no accept/decline step,
and no validation blocking stage completion (the article page warns about
missing galleys but does not stop you).

## Development note

This plugin was written by Justin Gonder working with Claude (Anthropic) in
Claude Code. Every step was verified against a running Janeway install, and the
test suite is part of the repository, but reviewers should know the code was
AI-assisted throughout.

## Licence

AGPL-3.0, matching Janeway and its plugins. See `LICENSE`.
