# OS-APS Typesetting Plugin — Architecture Spec

This is the design record: what was decided before and during the build, and the
roadmap beyond Phase 1. `HANDOFFS.md` is the record of what was learned building
it, including where the implementation deviates from this document and why. Where
the two disagree about how the code behaves today, `HANDOFFS.md` is the more
current.

## What this plugin does

A Janeway workflow plugin that replaces the built-in Typesetting stage with one that integrates the Open Source Academic Publishing Suite (OS-APS / SciFlow editor) into the typesetting workflow.

**OS-APS** (https://os-aps.de) is a self-hostable Node.js web application that converts Word/DOCX files to semantic HTML, then exports to PDF, HTML, JATS XML, and EPUB. It has a WYSIWYG editor for checking and correcting the conversion before export.

## Integration roadmap

This plugin is designed in three phases. Phase 1 is built; every decision in it
was made so as to leave Phases 2 and 3 open.

### Phase 1 — Manual handoff (built)
Janeway plugin shows files-for-typesetting. Typesetter downloads the DOCX, opens OS-APS in a new tab, works there, exports PDF/HTML, uploads outputs back to Janeway as galleys. No API required.

### Phase 2 — Embedded editor
Embed the SciFlow editor inside Janeway's typesetting stage using an iframe, following the pattern PKP is implementing in OJS 3.6 (see https://pkp.sfu.ca/2026/05/26/ojs-3-6-bringing-manuscript-editing-and-production-under-one-roof/).

### Phase 3 — Full API integration
Programmatic file push/pull between Janeway and OS-APS. Automatic galley creation from OS-APS exports. The `osaps_project_url` field on `OSAPSAssignment` is the hook for this phase.

## Plugin registration

```python
# plugin_settings.py
PLUGIN_NAME = "OS-APS Typesetting"
DISPLAY_NAME = "OS-APS Typesetting"
DESCRIPTION = "Typesetting workflow stage integrating the OS-APS publishing suite"
AUTHOR = "CDL"
VERSION = "0.1"
SHORT_NAME = "osaps_typesetting"
MANAGER_URL = "osaps_typesetting_manager"
JANEWAY_VERSION = "1.8"
IS_WORKFLOW_PLUGIN = True
JUMP_URL = "osaps_typesetting_article"
HANDSHAKE_URL = "osaps_typesetting_articles"
ARTICLE_PK_IN_HANDSHAKE_URL = True
STAGE = "osaps_typesetting"
KANBAN_CARD = "osaps_typesetting/elements/card.html"
DASHBOARD_TEMPLATE = "osaps_typesetting/elements/dashboard.html"
```

## Directory structure

In an install, the plugin sits in Janeway's plugin directory. The directory name
is the Django app label and must be exactly `osaps_typesetting`. In this git
repository the same files sit at the repository root, alongside `README.md`,
`LICENSE`, `SPEC.md`, `HANDOFFS.md` and `.gitignore`, so a clone drops straight
into place.

```
src/plugins/osaps_typesetting/
├── __init__.py
├── plugin_settings.py
├── models.py
├── views.py
├── urls.py
├── forms.py
├── logic.py
├── security.py               # the plugin's two access decorators
├── admin.py
├── tests.py
├── test_urls.py              # mounts the plugin's URLs for tests; see its docstring
├── migrations/
│   ├── __init__.py
│   └── 0001_initial.py
├── install/
│   └── settings.json         # journal-level setting: osaps_instance_url
├── templatetags/
│   ├── __init__.py
│   └── osaps_typesetting_tags.py   # counts for the dashboard and kanban card
└── templates/osaps_typesetting/
    ├── articles.html         # handshake URL — list of articles in this stage
    ├── article.html          # jump URL — main management view
    ├── assign.html           # assign a typesetter, or edit the assignment
    ├── assignments.html      # a typesetter's own task list
    ├── assignment.html       # typesetter's task view
    ├── edit_galley.html      # replace a galley, attach figures and a stylesheet
    ├── manager.html          # plugin settings/manager view
    └── elements/
        ├── breadcrumbs.html
        ├── card.html         # kanban card
        ├── dashboard.html    # dashboard widget
        ├── status.html       # assignment status label, used by four pages
        └── title_sub.html
```

## Models

Use fresh models in this plugin's own models.py. Do NOT import or extend models from
src/typesetting/. Plugin isolation is worth the modest duplication.

```python
class OSAPSRound(models.Model):
    """One or more rounds of typesetting per article."""
    article = models.ForeignKey(
        'submission.Article',
        on_delete=models.CASCADE,
    )
    round_number = models.IntegerField(default=1)
    date_started = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-round_number']


class OSAPSAssignment(models.Model):
    """
    A typesetting assignment within a round.
    Tracks files-for-typesetting, galleys created, and the OS-APS session.
    """
    round = models.OneToOneField(
        OSAPSRound,
        on_delete=models.CASCADE,
    )
    manager = models.ForeignKey(
        'core.Account',
        on_delete=models.SET_NULL,
        null=True,
        related_name='osaps_managed_assignments',
    )
    typesetter = models.ForeignKey(
        'core.Account',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='osaps_typesetting_assignments',
    )
    assigned = models.DateTimeField(auto_now_add=True)
    accepted = models.DateTimeField(null=True, blank=True)
    due = models.DateField(null=True, blank=True)
    completed = models.DateTimeField(null=True, blank=True)
    cancelled = models.DateTimeField(null=True, blank=True)

    # Files flowing into OS-APS
    files_to_typeset = models.ManyToManyField(
        'core.File',
        blank=True,
        related_name='osaps_assignments',
    )

    # Galleys produced in OS-APS and uploaded back
    galleys_created = models.ManyToManyField(
        'core.Galley',
        blank=True,
        related_name='osaps_assignments',
    )

    # Phase 3 hook: stores the OS-APS project URL once API integration is added.
    # Blank in Phase 1. Do not remove this field.
    osaps_project_url = models.URLField(blank=True)

    task = models.TextField(blank=True)
    typesetter_note = models.TextField(blank=True)
```

### CharField rules (CDL code review requirement)
- `null=True` is never used on CharField or TextField — use `blank=True` only
- `max_length` defaults to 250 unless domain knowledge says otherwise
- `null=True` is appropriate on ForeignKey and URLField

## Key views

Plugin URLs are mounted by `core/include_urls.py` under
`plugins/<slugify(DISPLAY_NAME)>/`, so with `DISPLAY_NAME = "OS-APS Typesetting"`
the prefix is `/plugins/os-aps-typesetting/`.

| View name | URL | Purpose |
|---|---|---|
| `osaps_typesetting_articles` | `/plugins/os-aps-typesetting/` | Handshake — lists articles in this stage |
| `osaps_typesetting_article` | `/plugins/os-aps-typesetting/article/<id>/` | Jump — main management view |
| `osaps_typesetting_assign` | `/plugins/os-aps-typesetting/article/<id>/assign/` | Assign typesetter |
| `osaps_typesetting_assignments` | `/plugins/os-aps-typesetting/assignments/` | A typesetter's own task list |
| `osaps_typesetting_assignment` | `/plugins/os-aps-typesetting/assignment/<id>/` | Typesetter task view |
| `osaps_typesetting_download_file` | `/plugins/os-aps-typesetting/assignment/<id>/file/<id>/` | Serve an assignment file to the typesetter |
| `osaps_typesetting_upload_galley` | `/plugins/os-aps-typesetting/article/<id>/galley/upload/` | Upload exported file as galley |
| `osaps_typesetting_edit_galley` | `/plugins/os-aps-typesetting/article/<id>/galley/<id>/edit/` | Replace a galley, attach the figures an HTML galley references, attach a stylesheet |
| `osaps_typesetting_complete` | `/plugins/os-aps-typesetting/article/<id>/complete/` | Complete stage, advance workflow |
| `osaps_typesetting_manager` | `/plugins/os-aps-typesetting/manager/` | Plugin settings (OS-APS instance URL) |

## Phase 1 typesetter workflow

Opening the jump view on an article opens round 1 automatically, so work can
begin without anything having been assigned.

1. **Optionally**, a manager assigns a typesetter via `osaps_typesetting_assign`.
   Assignment is optional throughout: many journals have no dedicated typesetter,
   and an editor may open the stage and do the work themselves. Nothing below
   requires an assignment to exist.
2. An assigned typesetter finds their work at `osaps_typesetting_assignments` and
   opens the task at `osaps_typesetting_assignment`:
   - Files for typesetting listed with download buttons
   - "Open OS-APS" button linking to configured OS-APS instance (from journal setting `osaps_instance_url`)
   - Standard `<input type="file">` upload form for importing outputs back as galleys
   - **No custom JavaScript** — standard HTML form POST only (CDL code review requirement)
3. The exported PDF/HTML is uploaded; the plugin calls
   `production.logic.save_galley()` and, when the upload came from an assignment,
   adds the galley to `assignment.galleys_created`. An HTML galley is not
   publishable until its figures are attached at `osaps_typesetting_edit_galley`.
4. Manager reviews galleys at `osaps_typesetting_article` and clicks Complete
5. `logic.complete_stage()` fires `ON_WORKFLOW_ELEMENT_COMPLETE` to advance the workflow

## Journal-level settings (install/settings.json)

`utils.install.update_settings()` requires the nested shape used by
`utils/install/journal_defaults.json`; a flat `{"name": …, "types": …}` object
raises `KeyError` on `item["group"]`. The type is `char`, which
`core.forms.GeneratedSettingForm` renders as a `TextInput` — `text` would give a
`Textarea` and `rich-text` a WYSIWYG box, neither of which suits a single URL.
Janeway's own URL settings (`publisher_url`, `privacy_policy_url`,
`external_newsletter_signup_url`) all use `char`.

```json
[
  {
    "group": {
      "name": "osaps_typesetting"
    },
    "setting": {
      "name": "osaps_instance_url",
      "pretty_name": "OS-APS Instance URL",
      "description": "URL of the OS-APS instance typesetters will use. Use the public demo or your self-hosted instance.",
      "type": "char",
      "is_translatable": false
    },
    "value": {
      "default": "https://os-aps.sciflow.net/start"
    }
  }
]
```

`editable_by` is omitted, so `update_settings()` applies its default of
`["editor", "journal-manager"]`.

## Completing the stage

Originally specified as `complete_assignment(assignment, request)`. It is
implemented as `complete_stage(article, request)`, keyed on the article rather
than the assignment, because an article can reach completion with no assignment
at all — see the workflow above. Any open assignment is closed on the way through.

```python
# logic.py
from events import logic as event_logic

def complete_stage(article, request):
    current_round = get_current_round(article)
    assignment = get_assignment(current_round)

    if assignment and not assignment.completed and not assignment.cancelled:
        assignment.completed = timezone.now()
        assignment.save()

    # Without this guard a journal that has removed the element gets an
    # unhandled failure rather than a warning. Follows typesetting/logic.py.
    if not request.journal.element_in_workflow(
        element_name=plugin_settings.PLUGIN_NAME,
    ):
        messages.add_message(request, messages.WARNING, "...")
        return redirect(reverse("core_dashboard"))

    return event_logic.Events.raise_event(
        event_logic.Events.ON_WORKFLOW_ELEMENT_COMPLETE,
        task_object=article,
        handshake_url=plugin_settings.HANDSHAKE_URL,
        request=request,
        article=article,
        switch_stage=True,
    )
```

Completing the typesetter's *task* is a separate, smaller action —
`logic.complete_typesetter_task()` — which hands the work back to the editor
without advancing the stage.

## Galley creation

Use `production.logic.save_galley()` — do not re-implement file saving logic.

```python
from production import logic as production_logic

def create_galley_from_upload(article, request, uploaded_file, label=None, public=True):
    return production_logic.save_galley(
        article=article,
        request=request,
        uploaded_file=uploaded_file,
        is_galley=True,
        label=label,
        public=public,
    )
```

Janeway derives a label from the file type when none is given. After an HTML
galley is saved or replaced, `logic.rewrite_remote_image_sources()` rewrites the
absolute OS-APS asset URLs in its markup to local filenames; see `HANDOFFS.md`
for why that is necessary and what it does not do.

## What NOT to do

- Do not write custom JavaScript
- Do not import models from src/typesetting/ 
- Do not use null=True on CharField or TextField
- Do not modify auto-generated migrations
- Do not open a draft PR to the upstream Janeway repo until the work is reviewed by at least two CDL developers

## Build order

1. Plugin skeleton: directory structure + plugin_settings.py + empty files + __init__.py files
2. Models + migration
3. install_plugins management command test
4. Core views: articles list (handshake) + article detail (jump)
5. Assign typesetter view + form
6. Typesetter task view + galley upload
7. Complete stage + workflow advancement
8. Templates for all views
9. Kanban card + dashboard widget
10. Manager view + OS-APS instance URL setting
11. Test end-to-end in local Janeway, and write `tests.py`

All eleven steps are complete as of 29 July 2026. `HANDOFFS.md` records what was
learned building each one, including where the implementation deviates from this
spec and why.
