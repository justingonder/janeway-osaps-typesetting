# OS-APS Typesetting Plugin — Session Handoff Notes

Running notes for future work sessions. `SPEC.md` is the design record; this file
is the "things we learned while building it" record. Add to it as you go.

Last updated: 30 July 2026.

## Status

**Phase 1 is complete.** All eleven steps of the build order are done and
`tests.py` holds 90 passing tests:

```
python src/manage.py test plugins.osaps_typesetting.tests
```

Note the module path — `test plugins.osaps_typesetting` fails on a namespace
package; see "Testing a plugin" below.

What is left is not building but review. Phase 1 has not been read by anyone
else, and CDL requires two developers to review before any upstream PR. The
deferred items are under "Open questions": notifications, an accept/decline
step, pre-completion checks and galley delete.

When picking the work up again, run Django's system checks first, and remember
that installing or re-registering the plugin needs a server restart — as does
adding any new module or package to it.

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
9. ✅ Kanban card + dashboard widget — minimal versions had to be pulled forward
   early (see below); counts added and verified 29 July 2026
10. ✅ Manager view + OS-APS instance URL setting — verified 29 July 2026
11. ✅ `tests.py` (90 tests) + end-to-end smoke check of the real install,
    29 July 2026

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

`src/plugins/*` is in the Janeway repo's `.gitignore` (line 83, no negation), so
**none of this plugin is tracked by the Janeway git repo**. `git status` run from
the Janeway root shows a clean tree no matter what you change here. This is
normal for Janeway — plugins live in their own repositories.

**This directory is its own git repository**, published at
<https://github.com/justingonder/janeway-osaps-typesetting> on 30 July 2026.
Run `git` commands from inside the plugin directory and they apply to the plugin;
run them from the Janeway root and they apply to Janeway.

Plugin files sit at the repository root, matching upstream Janeway plugins, so it
clones straight into place:
`git clone <url> src/plugins/osaps_typesetting`. The directory name is the Django
app label and must be exactly that.

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

- **Galley controls on the kanban card.** The card now shows the round number and
  galley count, but there is no way to act on an article from the board itself.
  Core's card does not offer that either, so this is probably fine.
## Implementation notes

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

## Testing a plugin (Step 11)

Four things about the test environment cost real time; none are obvious.

**`test plugins.osaps_typesetting` does not work.** `src/plugins/` has no
`__init__.py`, so it is a namespace package, and unittest's directory discovery
does `os.path.abspath(module.__file__)` on it and dies with
`TypeError: expected str, bytes or os.PathLike object, not NoneType`. Name the
module: `test plugins.osaps_typesetting.tests`.

**Plugin URLs are not registered under the test runner.** `core/include_urls.py`
mounts a plugin only if an enabled `Plugin` row exists *when that module is
imported*, and the test database is created empty, so every plugin view name —
and every redirect inside the views — raises `NoReverseMatch`. `test_urls.py`
solves it by mounting the plugin alongside core's patterns, and the tests set
`ROOT_URLCONF` to it. Build that module on **`core.urls`**, not
`core.include_urls`: `core.urls` is the real ROOT_URLCONF and adds the admin,
summernote, hijack and — under `settings.IN_TEST_RUNNER` — the debug toolbar,
whose middleware otherwise fails to reverse its own `djdt` namespace while
rendering any page. That one mistake accounted for 27 of the first run's errors.

**Never put a `Mock` in a template context.** Django's template variable
resolution calls anything callable it resolves, and a `Mock` is callable, so
`{{ request.user.is_staff }}` silently becomes an auto-created attribute of
`request()` — a truthy `Mock`. Every role check passes, for every user, and the
tests "pass" while asserting nothing. `typesetting/tests.py`'s
`prepare_request_with_user` is fine for security decorators, which only touch the
request from plain Python, but not for rendering. Use
`utils.testing.helpers.get_request()`, which returns a real `HttpRequest`.
`OSAPSTestCase` offers both, `mock_request` and `template_request`.

**Test file writes land in the development tree.** `File.self_article_path()` is
`settings.BASE_DIR/files/articles/<pk>/`, and article pks in the test database
start at 1 — the same directory as development article 1. Tests that write real
bytes override `BASE_DIR` to a temporary directory. Do it per test method, not on
the class: `plugin_settings.install()` resolves `install/settings.json` relative
to `BASE_DIR` and would not find it.

Also worth knowing: `make check` runs the whole Janeway suite (`make test` is not
a target), and **ruff cannot be run in this container** — it segfaults under qemu
on an arm64 host, and there is no host install.

## Dashboard and kanban counts (Step 9)

**Elements get almost no context, so counts have to come from tags.**
`templates/admin/core/dashboard.html:166-170` includes the dashboard element with
only the ambient context, and `kanban.html:60` adds just `article`. The plugin
therefore has a `templatetags/osaps_typesetting_tags.py` library, following
`typesetting/templatetags/role_count.py`. The queries themselves live in
`logic.py` (`articles_in_stage_count`, `open_assignment_count`) so they can be
tested without rendering a template; the tags are thin wrappers.

**A new `templatetags` package needs a server restart**, like any new module —
the autoreloader only watches what has already been imported. Template *edits*
inside it do not.

**Tag names are prefixed `osaps_`.** `{% load %}` is per-template so there is no
hard conflict, but core's `typesetting_tasks_count` and `articles_in_stage_count`
render on the same dashboard page and the unprefixed names would be genuinely
ambiguous to read.

**`user_has_role` defaults to `staff_override=True`, which staff match for every
role.** Core's typesetting widget takes that at face value, so every staff editor
is told "You have 0 Typesetting tasks". Ours passes `staff_override=False` for the
typesetter check and shows the task button to real typesetters always (it is their
page even when empty) and to staff only when they actually have work. The
condition is `typesetter or request.user.is_staff and num_open_tasks`; `and` binds
tighter than `or` in Django templates, and all six input combinations were
verified on 29 July 2026. This deliberately deviates from core.

**`{# … #}` is single-line only.** The Step 9 dashboard widget shipped with a
six-line `{#` comment explaining the `staff_override` decision. Django's
tokenizer matches comments with `{#.*?#}` and no `re.DOTALL`, so a multi-line one
never matches and the whole block renders as **visible text on the dashboard**.
Fixed 29 July 2026 by switching to `{% comment %}`, and caught by `tests.py`
rather than by eye — the manual Step 9 check extracted only the markup inside the
widget's box, and the comment sat just outside it. Use `{% comment %}` for
anything longer than one line.

Related trap when asserting on page content: under `DEBUG` the django debug
toolbar embeds template **source**, including this plugin's, into every page as
JSON for its template panel. Scanning a whole page for `{%` finds that payload,
not a rendering fault. Scope such assertions to the plugin's own markup.

**`article.osapsround_set.first.osapsassignment` is safe in a template even with
no assignment.** The reverse one-to-one raises `ObjectDoesNotExist`, which sets
`silent_variable_failure = True`, so the template renders it as empty rather than
500ing. Do not "fix" this with a `try`/`except` in a tag.

## Settings and the manager view (Step 10)

**The setting type is `char`, not `text`.** `core.forms.GeneratedSettingForm`
maps `char` → `TextInput`, `text` → `Textarea` and `rich-text` → a WYSIWYG box.
Every URL setting in `utils/install/journal_defaults.json` (`publisher_url`,
`privacy_policy_url`, `external_newsletter_signup_url`) is `char`, so a single
URL wants `char`. The earlier note here guessing `text` was wrong.

**`update_settings()` does update an existing `Setting` row's metadata.**
`utils/install.py:58-62` compares `types`, `pretty_name`, `description` and
`is_translatable` against the JSON and saves any that differ, so changing the
type in `install/settings.json` and re-running `install_plugins` is enough — no
hand-editing of the database. Existing **values** are left alone: the value is
only written when the `SettingValue` is created, or when
`overwrite_with_defaults=True`.

**`editable_by` is only written when the `SettingValue` is created**
(`utils/install.py:78-89`), inside the same branch as the default value. Ours was
populated on the first install, with the default `["editor", "journal-manager"]`
because the JSON omits the key. Verified 29 July 2026: a non-staff editor and a
journal-manager both pass, a typesetter does not. If you ever need to change
`editable_by` on an existing setting, re-running `install_plugins` will **not**
do it.

**`core.logic.user_can_edit_setting` takes a `SettingValue`, not a `Setting`.**
It reads `.editable_by`, which on `SettingValue` is a property returning a set of
role slugs (`core/models.py:1231`); on `Setting` it is the M2M manager, and
passing one raises `TypeError: 'ManyRelatedManager' object is not iterable`.
`logic.get_settings_to_edit()` passes the `SettingValue` returned by
`setting_handler.get_setting`, matching `core.logic.get_settings_to_edit`.

**The manager view takes no arguments.** `core/views.py:2184` does
`reverse(manager_url)` with no args when building the plugin manager page, so
`MANAGER_URL` must resolve without them. Before this step the name existed in
`plugin_settings.py` with no URL behind it, and the plugin was quietly listed
under "failed to load" on `/manager/plugins/`. It now appears in the normal list.

**We deliberately do not call `clear_cache()` after saving.** Core's settings
views do (`core/views.py:2028`), but `utils.shared.clear_cache` is
`cache.clear()` — it wipes the entire Django cache for every journal in the
install. `setting_handler` does no caching of its own and the instance URL is
read fresh on each request, so there is nothing stale to clear.

## Standing constraints (from CDL code review)

- No custom JavaScript — standard HTML form POSTs only
- No imports from `src/typesetting/`; this plugin keeps its own models
- No `null=True` on `CharField`/`TextField`
- Do not hand-edit auto-generated migrations
- Two CDL developers must review before any upstream PR; no draft/WIP PRs to the
  Janeway repo
- PR descriptions must be transparent about AI involvement
