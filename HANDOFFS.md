# OS-APS Typesetting Plugin — Session Handoff Notes

Running notes for future work sessions. `SPEC.md` is the design record; this file
is the "things we learned while building it" record. Add to it as you go.

Last updated: 28 July 2026.

## Start here next session

Steps 1–8 of the build order are done and verified. Remaining: **Step 9**
(dashboard article counts), **Step 10** (manager view and the OS-APS instance
URL setting, including changing its type from `rich-text` to `text`), and
**Step 11** (end-to-end test, plus the plugin's first `tests.py`).

Before anything else: `make command CMD="check"` from the repo root, and
remember that installing or re-registering the plugin needs a server restart.

The local fixture is article 1 on `pawprints`, in the `osaps_typesetting`
stage, round 1, assigned to Tom Tsetter, with the real OS-APS HTML export
uploaded as galley 3. That galley still reports one missing figure
(`image1.png` after rewriting) — attaching it on the galley edit page is a good
first manual check that everything still works.

## Where the build is

Build order is in `SPEC.md`. Steps 1–4 are done:

1. ✅ Plugin skeleton
2. ✅ Models + initial migration (`0001_initial`, applied)
3. ✅ `install_plugins` verified — Plugin row, setting, setting value all created
4. ✅ Core views — `articles` (handshake) + `article` (jump), URLs, thin
   templates. Verified end to end against a real article on 28 July 2026:
   list, kanban card, jump view, round auto-creation
5. ✅ Assign typesetter view + form — verified end to end on 28 July 2026,
   including create, edit, validation, and manager preservation
6. ✅ Typesetter task view + galley upload — verified 28 July 2026 as a user
   holding only the `typesetter` role, including the security boundaries.
   Also added `osaps_typesetting_assignments` (a typesetter's own task list)
   and a typesetter branch in the dashboard widget, so the task view is
   reachable in the UI. `SPEC.md`'s view table was updated to match.
7. ✅ Complete stage + workflow advancement — verified 28 July 2026; article
   advanced `osaps_typesetting` → `pre_publication` and the fixture was restored
8. ✅ Templates for all views — rebuilt 28 July 2026 and rendered as both an
   editor and a typesetter-only account (current ones are placeholders)
9. 🟡 Kanban card + dashboard widget — minimal versions exist (had to be pulled
   forward, see below); no article counts yet
10. ⬜ Manager view + OS-APS instance URL setting
11. ⬜ End-to-end test in local Janeway

## Environment gotchas

**Restart the dev server after `install_plugins`.** This cost us a confusing
`NoReverseMatch` on `/workflow/` on 28 July 2026. Plugin registration happens
once per process, at startup:

- `core/janeway_global_settings.py:109` builds `INSTALLED_APPS` by scanning
  `src/plugins/` on disk at settings-import time
- `core/include_urls.py` calls `plugin_loader.load()`, which only registers a
  plugin that already has an **enabled Plugin row in the database**

So a server started before the plugin existed (or before it was installed) has
no app, no template dir, no URLs and no workflow registration for it — while the
database may already have a workflow element pointing at
`osaps_typesetting_articles`. `templates/admin/core/nav.html:75` reverses every
workflow element's `handshake_url`, so the whole admin nav 500s until restart.
Django's autoreloader does not rescue you: it only watches modules that have
already been imported, and a brand-new package has not been.

**Order of operations when the plugin changes shape:** `makemigrations` →
`migrate` → `install_plugins` → **restart the server**.

**`KANBAN_CARD` and `DASHBOARD_TEMPLATE` in `plugin_settings.py` are promises,
not options.** Declaring a path there without creating the file 500s the admin
dashboard and kanban board for every user of the journal as soon as the workflow
element is added — this bit us on 28 July 2026 with `TemplateDoesNotExist` at
`/dashboard/`. `templates/admin/core/dashboard.html:166-170` guards the include
with `{% if element.settings.dashboard_template %}`, which only tests that the
string is non-empty; `templates/admin/core/kanban.html:60` does not guard at all.
Both element templates now exist. If you add another template constant to
`plugin_settings.py`, create the file in the same commit.

**Run `make` from the repo root**, not from inside `src/` or the plugin dir.
Django itself runs in Docker (`make command CMD="<django command>"`); there is no
local virtualenv on this machine.

## Version control

`src/plugins/*` is in the repo's `.gitignore` (line 83, no negation), so **none
of this plugin is tracked by the Janeway git repo**. `git status` shows a clean
tree no matter what you change here. This is normal for Janeway — plugins live in
their own repositories.

Plan of record: move the plugin to its own repo once Phase 1 is tested and we are
happy with it. Until then, be aware that nothing here is backed up by git and
there is no history to fall back on. The CDL two-developer review needs the
plugin in its own repo.

## Decisions made while building

**Round 1 is opened automatically by the jump view** (28 July 2026). The first
time an editor opens `osaps_typesetting_article`, `logic.new_round()` runs and
the view redirects to itself. This matches the core typesetting stage. Rationale:
many journals have no dedicated typesetter — editors jump into the stage and do
the work themselves — so nothing should have to be assigned before work can start.

*Implication for Step 5:* assigning a typesetter must stay optional. Do not make
the assign view a precondition for the typesetter task view or galley upload.
`OSAPSAssignment.typesetter` is already `null=True, blank=True`; note that
`manager` is `null=True` but **not** `blank=True`, so a ModelForm will require it
— decide deliberately when building the form.

**URLs are mounted under `/plugins/os-aps-typesetting/`**, not
`osaps-typesetting`. `core/include_urls.py` uses
`Plugin.best_name(slug=True)` = `slugify(DISPLAY_NAME.lower())`, and
`DISPLAY_NAME` is `"OS-APS Typesetting"`. Changing `DISPLAY_NAME` changes every
plugin URL. `SPEC.md`'s URL table was corrected to match.

**`install/settings.json` does not use the shape given in `SPEC.md`.**
`utils.install.update_settings()` requires the nested
`{"group": …, "setting": …, "value": …}` shape used by
`utils/install/journal_defaults.json`; the flat shape in the spec raises
`KeyError` on `item["group"]`. Values are unchanged from the spec. Setting group
name is `osaps_typesetting`.

## OS-APS HTML exports and figures

Real OS-APS exports reference their images by **absolute URL on the OS-APS
server**, not by relative filename:

```html
<img id="image1.png"
     src="https://os-aps.sciflow.net/export/asset/neighborly-curses-dc889b0a-.../examplesdocument%2Fmedia%2Fimage1.png">
```

Two consequences:

1. `Galley.has_missing_image_files()` (`core/models.py:1697`) matches on
   `os.path.basename(src)`, which for that URL is the entire percent-encoded
   segment `examplesdocument%2Fmedia%2Fimage1.png`. That is the name an
   attached image must have for Janeway to consider the figure present.
2. Left alone, a published article would hotlink its figures from the OS-APS
   instance. **Resolved 28 July 2026:** `logic.rewrite_remote_image_sources()`
   rewrites any absolute `http(s)` image reference to the decoded final path
   segment (`image1.png`) when an HTML galley is uploaded or replaced, so the
   expected filename is sane and the images readers see are the local ones.
   Relative references and data URIs are left alone; `alt`, `id` and the rest
   of the markup are preserved. Assets are **not** fetched from OS-APS — that
   would mean Janeway calling out to the OS-APS server, which belongs in
   Phase 3.

   Known limitation: two references whose paths differ but whose final segment
   is the same (`a/fig.png` and `b/fig.png`) collapse to one local name.

**We deviate from core when attaching a named figure.**
`production.logic.save_galley_image()` keeps whatever the uploaded file was
called; `fixed=True` only warns when the mime type does not match. Core
therefore expects the typesetter to have named the file exactly right, which is
not reasonable for names like the one above. `views.edit_galley` renames the
saved image to the `file_name` the slot asked for, so "Attach as &lt;name&gt;"
does what it says. Verified: missing → attached → `has_missing_image_files()`
returns `[]`.

Also note `production.logic.save_galley()` runs `remove_css_from_html()` on
HTML uploads, stripping embedded CSS. That is why a separate stylesheet upload
exists on the galley edit page.

## Verification safety rules

On 28 July 2026 a verification script destroyed a real uploaded galley: it
identified "the galley I just created" with `assignment.galleys_created.first()`
on an unordered queryset, got a **pre-existing** galley instead, mutated it, and
then deleted it. `core.models.File.delete()` unlinks the file from disk and
there is no `FileHistory` fallback, so it was unrecoverable.

Rules for any script that touches the dev database:

- Snapshot pre-existing object pks **before** acting.
- Identify created objects by set difference, never by `.first()` or `.last()`.
- Assert before deleting that the pk is not in the snapshot.
- Assert after cleanup that the pre-existing set is unchanged, and print it.

## Open questions

- **Galley controls we have not built.** The article page shows ID, Label,
  Filename, Public, Modified, Figures, Edit and Download. Core's typesetting
  stage also offers Preview, History, Delete and "Edit in Admin". Deferred by
  agreement on 28 July 2026; Delete is probably the next most useful.
- **Nobody is notified of anything.** No email is sent when a typesetter is
  assigned or when they complete a task. Core has a whole
  `typesetting/notifications/` module and separate "notify" views. `SPEC.md`
  does not mention notifications for Phase 1.
- **There is no accept/decline step.** `OSAPSAssignment.accepted` is never set;
  the typesetter just starts work. Core asks the typesetter to accept first.

- **Setting type for `osaps_instance_url` is `rich-text`** (from the spec). That
  renders a WYSIWYG editor for what is a single URL. `text` is probably the right
  type. Revisit at Step 10 when the manager view is built.
- **The dashboard widget shows no article count.** The core typesetting widget
  uses custom template tags (`typesetting_tasks_count` and friends in
  `typesetting/templatetags/`) to show "There are N articles in Typesetting".
  Ours is just a link. Add equivalent tags at Step 9 if we want the counts.
## Local test fixture

As of 28 July 2026 the dev database has article 1, "OS-APS Typesetting Test", in
the `osaps_typesetting` stage on the `pawprints` journal, walked through Review
and Copyediting by hand. It has exactly one file — pk 2, "Manuscript File",
`Example Document.docx` — which is the DOCX a typesetter would take into OS-APS.

There are **no `CopyeditAssignment` rows** for it, so `files_for_typesetting()`
returns only the manuscript file. The `Q(copyeditor_files__article=article)` leg
of that query is therefore still unexercised; if you want to test it, create a
copyedit assignment with an uploaded file.

Accounts: "Justin Gonder" (staff/editor) and "Tom Tsetter" (pk 2, holds the
`typesetter` role on `pawprints`, added 28 July 2026). Round 1 of article 1 has
an assignment to Tom Tsetter with `Example Document.docx` attached — this is the
fixture Steps 6 and 7 build on.

**The plugin serves its own files.** `security.logic.can_view_file` — which
guards Janeway's `article_file_download` — knows about core's production,
proofing and typesetting models but has no idea our `OSAPSAssignment` exists, so
a plugin typesetter is denied by it. The core typesetting stage has the same
problem and solves it with its own download views
(`typesetting_typesetter_download_file`), so we do too:
`views.download_file` serves files through `core.files.serve_any_file` after
checking the file belongs to the assignment, the article's figures, or an
existing galley. Do not switch these links to `article_file_download`.

**`security.py` holds the plugin's two decorators**, modelled on
`typesetting/security.py`: `typesetter_for_assignment_required` (views keyed on
`assignment_id`) and `typesetter_for_article_required` (views keyed on
`article_id`). Both admit editors, staff and production users, plus the assigned
typesetter whatever roles they hold.

**Template structure.** Shared pieces live in
`templates/osaps_typesetting/elements/`: `breadcrumbs.html`, `title_sub.html`
and `status.html` (the assignment status label, used by the list, the article
page, the task page and the kanban card). Pages extend `admin/core/base.html`
and fill `title`, `title-section`, `title-sub`, `breadcrumbs`, `body` and `js`.

The two list pages include Janeway's own `elements/datatables.html` for sorting
and search. That is a Janeway-maintained element, not JavaScript we wrote — the
plugin's templates contain no `<script>`, `onclick` or `javascript:` anywhere.

Editors download files through Janeway's `article_file_download`, which
`can_view_file` permits for editors and staff. Typesetters use the plugin's own
`osaps_typesetting_download_file`. Two different URLs on purpose; see above.

**Stage completion is keyed on the article, not the assignment.** `SPEC.md`
describes `complete_assignment(assignment, request)`, but an article can reach
completion with no assignment at all — an editor may have typeset it themselves
— so `logic.complete_stage(article, request)` takes the article and closes any
open assignment on the way through. It guards with
`request.journal.element_in_workflow(element_name=PLUGIN_NAME)` before raising
`ON_WORKFLOW_ELEMENT_COMPLETE`, following `typesetting/logic.py:231`; without
that guard a journal that removed the element gets an unhandled failure instead
of a warning.

**There are no pre-completion checks.** Core's typesetting stage validates
before completing (missing galleys, missing images, open tasks — see
`typesetting/logic.py:199`). Ours only *warns* in the template when there are no
galleys or the typesetter's task is still open; it never blocks. Consider
porting real checks if journals start completing articles with nothing attached.

**The `manager` field is set by the view, not the form.** `AssignmentForm` takes
`manager` and `typesetting_round` as constructor kwargs; `save()` applies the
round always and the manager only when the assignment does not already have one,
so editing an assignment does not steal ownership from whoever created it.

## Standing constraints (from CDL code review)

- No custom JavaScript — standard HTML form POSTs only
- No imports from `src/typesetting/`; this plugin keeps its own models
- No `null=True` on `CharField`/`TextField`
- Do not hand-edit auto-generated migrations
- Two CDL developers must review before any upstream PR; no draft/WIP PRs to the
  Janeway repo
- PR descriptions must be transparent about AI involvement
