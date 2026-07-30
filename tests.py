"""
Tests for the OS-APS Typesetting plugin.

Run with:

    DB_VENDOR=sqlite make command CMD="test plugins.osaps_typesetting.tests"

Note the module path: `plugins` has no __init__.py, so the shorter
`test plugins.osaps_typesetting` label makes unittest's discovery fall over on a
namespace package.

Two environment facts shape everything here:

* Plugin URLs are not registered under the test runner, because the test
  database has no `Plugin` row when the URLconf is imported. The tests point
  ROOT_URLCONF at the plugin's `test_urls` module instead. See its docstring.
* Files live under `settings.BASE_DIR/files/articles/<pk>/`, which is the real
  development tree, and test article pks start at 1. Tests that write real bytes
  override BASE_DIR to a temporary directory so they cannot touch development
  files. Everything else uses File rows with no file on disk.
"""

import os
import shutil
import tempfile
from unittest.mock import Mock

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpRequest
from django.template import Context, Template
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import models as core_models
from plugins.osaps_typesetting import logic, models, plugin_settings, security
from submission import models as submission_models
from utils import setting_handler
from utils.testing import helpers

PLUGIN_URLCONF = "plugins.osaps_typesetting.test_urls"


@override_settings(ROOT_URLCONF=PLUGIN_URLCONF, URL_CONFIG="domain")
class OSAPSTestCase(TestCase):
    """
    Fixtures shared by every test class below. Subclasses inherit the settings
    overrides above, so plugin view names are reversible and the journal is
    resolved from the request's domain rather than a path prefix.
    """

    @classmethod
    def setUpTestData(cls):
        helpers.create_press()
        cls.journal_one, cls.journal_two = helpers.create_journals()
        helpers.create_roles(
            [
                "editor",
                "production",
                "typesetter",
                "copyeditor",
                "author",
                "journal-manager",
            ]
        )

        # Creates the Plugin row, the setting group, the setting and its
        # default value, exactly as the install_plugins command would.
        plugin_settings.install()

        cls.editor = helpers.create_user(
            "editor@osaps.test",
            roles=["editor"],
            journal=cls.journal_one,
            **{"is_active": True, "first_name": "Ed", "last_name": "Itor"},
        )
        cls.staff_user = helpers.create_user(
            "staff@osaps.test",
            roles=["author"],
            journal=cls.journal_one,
            **{"is_active": True, "is_staff": True},
        )
        cls.production_user = helpers.create_user(
            "production@osaps.test",
            roles=["production"],
            journal=cls.journal_one,
            **{"is_active": True},
        )
        cls.typesetter = helpers.create_user(
            "typesetter@osaps.test",
            roles=["typesetter"],
            journal=cls.journal_one,
            **{"is_active": True, "first_name": "Tom", "last_name": "Tsetter"},
        )
        cls.other_typesetter = helpers.create_user(
            "other.typesetter@osaps.test",
            roles=["typesetter"],
            journal=cls.journal_one,
            **{"is_active": True},
        )
        cls.unrelated_user = helpers.create_user(
            "author@osaps.test",
            roles=["author"],
            journal=cls.journal_one,
            **{"is_active": True},
        )

        cls.article = helpers.create_article(
            cls.journal_one,
            title="An Article in OS-APS Typesetting",
            stage=plugin_settings.STAGE,
        )
        cls.other_journal_article = helpers.create_article(
            cls.journal_two,
            title="An Article on the Other Journal",
            stage=plugin_settings.STAGE,
        )

        cls.manuscript_file = core_models.File.objects.create(
            mime_type=(
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            ),
            original_filename="Example Document.docx",
            uuid_filename="uuid-manuscript.docx",
            label="Manuscript File",
            owner=cls.editor,
            article_id=cls.article.pk,
        )
        cls.article.manuscript_files.add(cls.manuscript_file)

        cls.figure_file = core_models.File.objects.create(
            mime_type="image/png",
            original_filename="image1.png",
            uuid_filename="uuid-image1.png",
            label="Figure",
            owner=cls.editor,
            article_id=cls.article.pk,
        )
        cls.article.data_figure_files.add(cls.figure_file)

        # A file belonging to the article but not offered for typesetting, for
        # checking that the download view refuses it.
        cls.unrelated_file = core_models.File.objects.create(
            mime_type="text/plain",
            original_filename="private.txt",
            uuid_filename="uuid-private.txt",
            label="Something else",
            owner=cls.editor,
            article_id=cls.article.pk,
        )

        # The plugin replaces core's typesetting element, so swap it out and
        # take its place in the order. That leaves prepublication after us,
        # which is what stage advancement needs.
        workflow = cls.journal_one.workflow()
        core_typesetting = workflow.elements.filter(element_name="typesetting")
        workflow.elements.remove(*core_typesetting)

        cls.workflow_element = core_models.WorkflowElement.objects.create(
            journal=cls.journal_one,
            element_name=plugin_settings.PLUGIN_NAME,
            handshake_url=plugin_settings.HANDSHAKE_URL,
            jump_url=plugin_settings.JUMP_URL,
            stage=plugin_settings.STAGE,
            article_url=True,
            order=2,
        )
        workflow.elements.add(cls.workflow_element)

        cls.round = models.OSAPSRound.objects.create(article=cls.article)
        cls.assignment = models.OSAPSAssignment.objects.create(
            round=cls.round,
            manager=cls.editor,
            typesetter=cls.typesetter,
        )
        cls.assignment.files_to_typeset.add(cls.manuscript_file)

    @staticmethod
    def template_request(user, journal):
        """
        A request for rendering templates with.

        It must be a real HttpRequest, not a Mock: Django's template variable
        resolution calls any callable it resolves, and a Mock is callable, so
        `request.user.is_staff` in a template becomes an auto-created -- and
        therefore truthy -- Mock attribute of `request()`. Every role check
        silently passes, for every user.
        """
        return helpers.get_request(user=user, journal=journal)

    @staticmethod
    def mock_request(user, journal, path="/a/fake/path/"):
        """
        A request dummy good enough for the security decorators, which only
        touch it from plain Python. Follows
        typesetting.tests.TestTypesetting.prepare_request_with_user. Do not use
        it to render a template -- see template_request.
        """
        request = Mock(HttpRequest)
        request.user = user
        request.journal = journal
        request.GET = Mock()
        request.GET.get = Mock(return_value=None)
        request.GET.urlencode = Mock(return_value="")
        request._messages = Mock()
        request.path = path
        request.path_info = path

        return request


class TestRoundsAndAssignments(OSAPSTestCase):
    def test_get_current_round_returns_highest_numbered_round(self):
        second = models.OSAPSRound.objects.create(
            article=self.article,
            round_number=2,
        )
        self.addCleanup(second.delete)

        self.assertEqual(logic.get_current_round(self.article), second)

    def test_get_current_round_is_none_without_a_round(self):
        self.assertIsNone(logic.get_current_round(self.other_journal_article))

    def test_new_round_numbers_from_one(self):
        new_round = logic.new_round(self.other_journal_article)
        self.addCleanup(new_round.delete)

        self.assertEqual(new_round.round_number, 1)

    def test_new_round_increments(self):
        new_round = logic.new_round(self.article)
        self.addCleanup(new_round.delete)

        self.assertEqual(new_round.round_number, 2)
        self.assertEqual(logic.get_current_round(self.article), new_round)

    def test_get_assignment_returns_the_rounds_assignment(self):
        self.assertEqual(logic.get_assignment(self.round), self.assignment)

    def test_get_assignment_is_none_for_a_round_with_no_assignment(self):
        bare_round = models.OSAPSRound.objects.create(
            article=self.other_journal_article,
        )
        self.addCleanup(bare_round.delete)

        self.assertIsNone(logic.get_assignment(bare_round))

    def test_get_assignment_is_none_for_no_round(self):
        self.assertIsNone(logic.get_assignment(None))

    def test_complete_typesetter_task_records_time_and_note(self):
        logic.complete_typesetter_task(self.assignment, note="All done.")
        self.assignment.refresh_from_db()

        self.assertIsNotNone(self.assignment.completed)
        self.assertEqual(self.assignment.typesetter_note, "All done.")


class TestFilesForTypesetting(OSAPSTestCase):
    def test_includes_manuscript_and_figure_files(self):
        files = logic.files_for_typesetting(self.article)

        self.assertIn(self.manuscript_file, files)
        self.assertIn(self.figure_file, files)

    def test_excludes_unrelated_files(self):
        self.assertNotIn(
            self.unrelated_file,
            logic.files_for_typesetting(self.article),
        )

    def test_includes_copyedited_files(self):
        """
        The Q(copyeditor_files__article=article) leg of the query. There were no
        copyedit assignments in the development fixture, so this was the one
        part of files_for_typesetting never exercised by hand.
        """
        copyeditor = helpers.create_user(
            "copyeditor@osaps.test",
            roles=["copyeditor"],
            journal=self.journal_one,
            **{"is_active": True},
        )
        assignment = helpers.create_copyedit_assignment(self.article, copyeditor)
        copyedited_file = core_models.File.objects.create(
            mime_type="text/plain",
            original_filename="copyedited.docx",
            uuid_filename="uuid-copyedited.docx",
            label="Copyedited file",
            owner=copyeditor,
            article_id=self.article.pk,
        )
        assignment.copyeditor_files.add(copyedited_file)

        self.assertIn(copyedited_file, logic.files_for_typesetting(self.article))

    def test_is_distinct(self):
        """
        A file reachable down more than one leg of the query must appear once.
        """
        assignment = helpers.create_copyedit_assignment(
            self.article,
            helpers.create_user(
                "copyeditor2@osaps.test",
                roles=["copyeditor"],
                journal=self.journal_one,
                **{"is_active": True},
            ),
        )
        assignment.copyeditor_files.add(self.manuscript_file)

        files = logic.files_for_typesetting(self.article)

        self.assertEqual(list(files).count(self.manuscript_file), 1)


class TestCounts(OSAPSTestCase):
    def test_articles_in_stage_count_matches_the_list(self):
        self.assertEqual(
            logic.articles_in_stage_count(self.journal_one),
            len(logic.articles_in_stage(self.journal_one)),
        )

    def test_articles_in_stage_is_scoped_to_the_journal(self):
        self.assertEqual(logic.articles_in_stage_count(self.journal_one), 1)
        self.assertEqual(logic.articles_in_stage_count(self.journal_two), 1)

        rows = logic.articles_in_stage(self.journal_one)

        self.assertEqual([row["article"] for row in rows], [self.article])

    def test_articles_in_stage_ignores_other_stages(self):
        self.article.stage = submission_models.STAGE_PROOFING
        self.article.save()
        self.addCleanup(self.reset_stage)

        self.assertEqual(logic.articles_in_stage_count(self.journal_one), 0)

    def reset_stage(self):
        self.article.stage = plugin_settings.STAGE
        self.article.save()

    def test_articles_in_stage_rows_carry_round_and_assignment(self):
        row = logic.articles_in_stage(self.journal_one)[0]

        self.assertEqual(row["round"], self.round)
        self.assertEqual(row["assignment"], self.assignment)
        self.assertEqual(row["galley_count"], 0)

    def test_open_assignment_count(self):
        self.assertEqual(
            logic.open_assignment_count(self.typesetter, self.journal_one),
            1,
        )

    def test_open_assignment_count_excludes_completed(self):
        self.assignment.completed = timezone.now()
        self.assignment.save()

        self.assertEqual(
            logic.open_assignment_count(self.typesetter, self.journal_one),
            0,
        )

    def test_open_assignment_count_excludes_cancelled(self):
        self.assignment.cancelled = timezone.now()
        self.assignment.save()

        self.assertEqual(
            logic.open_assignment_count(self.typesetter, self.journal_one),
            0,
        )

    def test_open_assignment_count_is_scoped_to_the_journal(self):
        self.assertEqual(
            logic.open_assignment_count(self.typesetter, self.journal_two),
            0,
        )

    def test_open_assignment_count_is_per_user(self):
        self.assertEqual(
            logic.open_assignment_count(self.other_typesetter, self.journal_one),
            0,
        )

    def test_open_assignment_count_handles_anonymous_and_missing_users(self):
        self.assertEqual(
            logic.open_assignment_count(AnonymousUser(), self.journal_one),
            0,
        )
        self.assertEqual(logic.open_assignment_count(None, self.journal_one), 0)


class TestSettings(OSAPSTestCase):
    def test_install_creates_the_setting_with_the_char_type(self):
        setting = core_models.Setting.objects.get(
            name="osaps_instance_url",
            group__name=plugin_settings.SETTING_GROUP_NAME,
        )

        # char renders as a TextInput in GeneratedSettingForm. text would give a
        # Textarea and rich-text a WYSIWYG box, neither of which suits a URL.
        self.assertEqual(setting.types, "char")

    def test_install_makes_the_setting_editable_by_editors_and_managers(self):
        setting_value = setting_handler.get_setting(
            plugin_settings.SETTING_GROUP_NAME,
            "osaps_instance_url",
            None,
        )

        self.assertEqual(
            setting_value.editable_by,
            {"editor", "journal-manager"},
        )

    def test_get_osaps_instance_url_falls_back_to_the_default(self):
        self.assertEqual(
            logic.get_osaps_instance_url(self.journal_one),
            "https://os-aps.sciflow.net/start",
        )

    def test_get_osaps_instance_url_prefers_a_journal_override(self):
        setting_handler.save_setting(
            plugin_settings.SETTING_GROUP_NAME,
            "osaps_instance_url",
            self.journal_one,
            "https://osaps.example.org/",
        )

        self.assertEqual(
            logic.get_osaps_instance_url(self.journal_one),
            "https://osaps.example.org/",
        )
        # Overriding one journal must not change another.
        self.assertEqual(
            logic.get_osaps_instance_url(self.journal_two),
            "https://os-aps.sciflow.net/start",
        )

    def test_get_settings_to_edit_allows_an_editor(self):
        settings_to_edit, group = logic.get_settings_to_edit(
            self.journal_one,
            self.editor,
        )

        self.assertEqual(
            [setting["name"] for setting in settings_to_edit],
            ["osaps_instance_url"],
        )
        self.assertEqual(group, plugin_settings.SETTING_GROUP_NAME)

    def test_get_settings_to_edit_refuses_a_typesetter(self):
        settings_to_edit, _group = logic.get_settings_to_edit(
            self.journal_one,
            self.typesetter,
        )

        self.assertEqual(settings_to_edit, [])


class TestCompleteStage(OSAPSTestCase):
    def test_complete_stage_advances_the_article(self):
        request = self.mock_request(self.editor, self.journal_one)

        logic.complete_stage(self.article, request)
        self.article.refresh_from_db()

        # Our element sits at order 2, so prepublication follows it.
        self.assertEqual(
            self.article.stage,
            submission_models.STAGE_READY_FOR_PUBLICATION,
        )

    def test_complete_stage_closes_an_open_assignment(self):
        request = self.mock_request(self.editor, self.journal_one)

        logic.complete_stage(self.article, request)
        self.assignment.refresh_from_db()

        self.assertIsNotNone(self.assignment.completed)

    def test_complete_stage_leaves_a_cancelled_assignment_alone(self):
        cancelled_at = timezone.now()
        self.assignment.cancelled = cancelled_at
        self.assignment.save()

        logic.complete_stage(
            self.article,
            self.mock_request(self.editor, self.journal_one),
        )
        self.assignment.refresh_from_db()

        self.assertIsNone(self.assignment.completed)

    def test_complete_stage_warns_when_the_element_is_not_in_the_workflow(self):
        """
        Guards the ON_WORKFLOW_ELEMENT_COMPLETE event, following
        typesetting/logic.py. Without the guard a journal that removed the
        element gets an unhandled failure rather than a warning.
        """
        workflow = self.journal_one.workflow()
        workflow.elements.remove(self.workflow_element)

        request = self.mock_request(self.editor, self.journal_one)
        response = logic.complete_stage(self.article, request)
        self.article.refresh_from_db()

        self.assertEqual(response.url, reverse("core_dashboard"))
        self.assertEqual(self.article.stage, plugin_settings.STAGE)


class TestRewriteRemoteImageSources(OSAPSTestCase):
    """
    OS-APS HTML exports reference their assets by absolute URL on the OS-APS
    server. These tests write real files, so BASE_DIR is redirected at a
    temporary directory: article pks in the test database start at 1 and would
    otherwise share a directory with development files.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp_dir, True)

    def make_html_galley(self, html):
        from core import files as core_files

        with override_settings(BASE_DIR=self.temp_dir):
            uploaded = SimpleUploadedFile(
                "export.html",
                html.encode("utf-8"),
                content_type="text/html",
            )
            file_object = core_files.save_file_to_article(
                uploaded,
                self.article,
                self.editor,
                is_galley=True,
            )
            galley = core_models.Galley.objects.create(
                article=self.article,
                file=file_object,
                label="HTML",
                type="html",
            )

            return galley

    def read_galley(self, galley):
        with override_settings(BASE_DIR=self.temp_dir):
            with open(galley.file.self_article_path(), encoding="utf-8") as handle:
                return handle.read()

    def test_absolute_source_is_rewritten_to_its_final_path_segment(self):
        galley = self.make_html_galley(
            '<html><body><img id="image1.png" alt="A figure" '
            'src="https://os-aps.example.org/export/asset/slug/'
            'doc%2Fmedia%2Fimage1.png"></body></html>'
        )

        with override_settings(BASE_DIR=self.temp_dir):
            rewritten = logic.rewrite_remote_image_sources(galley)

        self.assertEqual(len(rewritten), 1)
        self.assertEqual(rewritten[0][1], "image1.png")

        content = self.read_galley(galley)

        self.assertIn('src="image1.png"', content)
        # The rest of the markup survives.
        self.assertIn('alt="A figure"', content)
        self.assertIn('id="image1.png"', content)

    def test_relative_sources_are_left_alone(self):
        galley = self.make_html_galley(
            '<html><body><img src="figure2.png"></body></html>'
        )

        with override_settings(BASE_DIR=self.temp_dir):
            rewritten = logic.rewrite_remote_image_sources(galley)

        self.assertEqual(rewritten, [])
        self.assertIn('src="figure2.png"', self.read_galley(galley))

    def test_data_uris_are_left_alone(self):
        galley = self.make_html_galley(
            '<html><body><img src="data:image/png;base64,AAAA"></body></html>'
        )

        with override_settings(BASE_DIR=self.temp_dir):
            rewritten = logic.rewrite_remote_image_sources(galley)

        self.assertEqual(rewritten, [])
        self.assertIn("data:image/png;base64,AAAA", self.read_galley(galley))

    def test_non_html_galleys_are_skipped(self):
        pdf_file = core_models.File.objects.create(
            mime_type="application/pdf",
            original_filename="export.pdf",
            uuid_filename="uuid-export.pdf",
            label="PDF",
            owner=self.editor,
            article_id=self.article.pk,
        )
        galley = core_models.Galley.objects.create(
            article=self.article,
            file=pdf_file,
            label="PDF",
            type="pdf",
        )

        # Returns without opening anything, so the missing file does not matter.
        self.assertEqual(logic.rewrite_remote_image_sources(galley), [])

    def test_known_limitation_same_basename_collapses(self):
        """
        Documented in HANDOFFS.md: two references whose paths differ but whose
        final segment matches collapse to one local name. Asserted so that a
        future change to this behaviour is a visible test change.
        """
        galley = self.make_html_galley(
            "<html><body>"
            '<img src="https://os-aps.example.org/a%2Ffig.png">'
            '<img src="https://os-aps.example.org/b%2Ffig.png">'
            "</body></html>"
        )

        with override_settings(BASE_DIR=self.temp_dir):
            rewritten = logic.rewrite_remote_image_sources(galley)

        self.assertEqual({name for _, name in rewritten}, {"fig.png"})
        self.assertEqual(self.read_galley(galley).count('src="fig.png"'), 2)


class TestSecurityDecorators(OSAPSTestCase):
    def assert_passes(self, decorator, user, kwargs, journal=None):
        func = Mock()
        decorated = decorator(func)
        request = self.mock_request(user, journal or self.journal_one)

        decorated(request, **kwargs)

        self.assertTrue(
            func.called,
            "{0} should have admitted {1}".format(decorator.__name__, user),
        )

    def assert_denied(self, decorator, user, kwargs, journal=None):
        func = Mock()
        decorated = decorator(func)
        request = self.mock_request(user, journal or self.journal_one)

        with self.assertRaises(PermissionDenied):
            decorated(request, **kwargs)

        self.assertFalse(
            func.called,
            "{0} should have denied {1}".format(decorator.__name__, user),
        )

    # typesetter_for_assignment_required

    def test_assignment_decorator_admits_the_assigned_typesetter(self):
        self.assert_passes(
            security.typesetter_for_assignment_required,
            self.typesetter,
            {"assignment_id": self.assignment.pk},
        )

    def test_assignment_decorator_admits_managers(self):
        for user in (self.editor, self.staff_user, self.production_user):
            self.assert_passes(
                security.typesetter_for_assignment_required,
                user,
                {"assignment_id": self.assignment.pk},
            )

    def test_assignment_decorator_denies_an_unrelated_user(self):
        self.assert_denied(
            security.typesetter_for_assignment_required,
            self.unrelated_user,
            {"assignment_id": self.assignment.pk},
        )

    def test_assignment_decorator_denies_another_typesetter(self):
        self.assert_denied(
            security.typesetter_for_assignment_required,
            self.other_typesetter,
            {"assignment_id": self.assignment.pk},
        )

    def test_assignment_decorator_denies_a_cancelled_assignment(self):
        self.assignment.cancelled = timezone.now()
        self.assignment.save()

        self.assert_denied(
            security.typesetter_for_assignment_required,
            self.typesetter,
            {"assignment_id": self.assignment.pk},
        )

    def test_assignment_decorator_is_scoped_to_the_journal(self):
        """
        Janeway is multi-tenant: the same process serves every journal, so the
        assigned typesetter must not pass the check on a different journal.
        """
        self.assert_denied(
            security.typesetter_for_assignment_required,
            self.typesetter,
            {"assignment_id": self.assignment.pk},
            journal=self.journal_two,
        )

    def test_assignment_decorator_redirects_anonymous_users_to_login(self):
        func = Mock()
        decorated = security.typesetter_for_assignment_required(func)
        request = self.mock_request(AnonymousUser(), self.journal_one)

        response = decorated(request, assignment_id=self.assignment.pk)

        self.assertFalse(func.called)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("core_login"), response.url)

    # typesetter_for_article_required

    def test_article_decorator_admits_the_assigned_typesetter(self):
        self.assert_passes(
            security.typesetter_for_article_required,
            self.typesetter,
            {"article_id": self.article.pk},
        )

    def test_article_decorator_admits_managers(self):
        for user in (self.editor, self.staff_user, self.production_user):
            self.assert_passes(
                security.typesetter_for_article_required,
                user,
                {"article_id": self.article.pk},
            )

    def test_article_decorator_denies_an_unrelated_user(self):
        self.assert_denied(
            security.typesetter_for_article_required,
            self.unrelated_user,
            {"article_id": self.article.pk},
        )

    def test_article_decorator_denies_a_cancelled_assignment(self):
        self.assignment.cancelled = timezone.now()
        self.assignment.save()

        self.assert_denied(
            security.typesetter_for_article_required,
            self.typesetter,
            {"article_id": self.article.pk},
        )

    def test_article_decorator_is_scoped_to_the_journal(self):
        self.assert_denied(
            security.typesetter_for_article_required,
            self.typesetter,
            {"article_id": self.article.pk},
            journal=self.journal_two,
        )


class TestViews(OSAPSTestCase):
    def url(self, name, **kwargs):
        return reverse(name, kwargs=kwargs)

    def test_articles_list_is_open_to_editors_and_production(self):
        for user in (self.editor, self.production_user, self.staff_user):
            self.client.force_login(user)
            response = self.client.get(self.url("osaps_typesetting_articles"))

            self.assertEqual(response.status_code, 200)
            self.assertIn(
                self.article, [row["article"] for row in response.context["rows"]]
            )

    def test_articles_list_refuses_a_typesetter(self):
        self.client.force_login(self.typesetter)
        response = self.client.get(self.url("osaps_typesetting_articles"))

        self.assertNotEqual(response.status_code, 200)

    def test_article_view_renders(self):
        self.client.force_login(self.editor)
        response = self.client.get(
            self.url("osaps_typesetting_article", article_id=self.article.pk)
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["round"], self.round)
        self.assertEqual(response.context["assignment"], self.assignment)
        self.assertIn(self.manuscript_file, response.context["files"])

    def test_article_view_opens_round_one_on_first_visit(self):
        """
        An editor may typeset an article themselves, so opening the jump view
        must not require anything to have been assigned first.
        """
        article = helpers.create_article(
            self.journal_one,
            title="Not Yet Started",
            stage=plugin_settings.STAGE,
        )
        self.client.force_login(self.editor)

        response = self.client.get(
            self.url("osaps_typesetting_article", article_id=article.pk)
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            models.OSAPSRound.objects.filter(article=article).count(),
            1,
        )
        self.assertEqual(logic.get_current_round(article).round_number, 1)

    def test_article_view_404s_across_journals(self):
        self.client.force_login(self.editor)
        response = self.client.get(
            self.url(
                "osaps_typesetting_article",
                article_id=self.other_journal_article.pk,
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_assign_creates_an_assignment(self):
        article = helpers.create_article(
            self.journal_one,
            title="Needs A Typesetter",
            stage=plugin_settings.STAGE,
        )
        new_round = models.OSAPSRound.objects.create(article=article)
        self.client.force_login(self.editor)

        response = self.client.post(
            self.url("osaps_typesetting_assign", article_id=article.pk),
            {
                "typesetter": self.typesetter.pk,
                "due": "2026-12-01",
                "task": "Please typeset this.",
            },
        )

        self.assertEqual(response.status_code, 302)
        assignment = models.OSAPSAssignment.objects.get(round=new_round)
        self.assertEqual(assignment.typesetter, self.typesetter)
        self.assertEqual(assignment.manager, self.editor)
        self.assertEqual(assignment.task, "Please typeset this.")

    def test_assign_requires_a_typesetter(self):
        self.client.force_login(self.editor)
        response = self.client.post(
            self.url("osaps_typesetting_assign", article_id=self.article.pk),
            {"task": "No typesetter chosen."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("typesetter", response.context["form"].errors)

    def test_assign_offers_only_typesetters_of_this_journal(self):
        self.client.force_login(self.editor)
        response = self.client.get(
            self.url("osaps_typesetting_assign", article_id=self.article.pk)
        )
        offered = response.context["form"].fields["typesetter"].queryset

        self.assertIn(self.typesetter, offered)
        self.assertIn(self.other_typesetter, offered)
        self.assertNotIn(self.unrelated_user, offered)

    def test_assign_edit_does_not_steal_the_original_manager(self):
        """
        AssignmentForm applies the manager only when the assignment has none,
        so a second editor editing an assignment does not take it over.
        """
        self.client.force_login(self.production_user)
        self.client.post(
            self.url("osaps_typesetting_assign", article_id=self.article.pk),
            {"typesetter": self.other_typesetter.pk},
        )
        self.assignment.refresh_from_db()

        self.assertEqual(self.assignment.typesetter, self.other_typesetter)
        self.assertEqual(self.assignment.manager, self.editor)

    def test_assignments_list_shows_only_the_users_own_tasks(self):
        self.client.force_login(self.typesetter)
        response = self.client.get(self.url("osaps_typesetting_assignments"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.assignment, response.context["active_assignments"])

        self.client.force_login(self.other_typesetter)
        response = self.client.get(self.url("osaps_typesetting_assignments"))

        self.assertNotIn(self.assignment, response.context["active_assignments"])

    def test_assignments_list_splits_active_from_closed(self):
        self.assignment.completed = timezone.now()
        self.assignment.save()
        self.client.force_login(self.typesetter)

        response = self.client.get(self.url("osaps_typesetting_assignments"))

        self.assertNotIn(self.assignment, response.context["active_assignments"])
        self.assertIn(self.assignment, response.context["past_assignments"])

    def test_assignment_view_renders_for_the_typesetter(self):
        self.client.force_login(self.typesetter)
        response = self.client.get(
            self.url("osaps_typesetting_assignment", assignment_id=self.assignment.pk)
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.manuscript_file, response.context["files"])
        self.assertEqual(
            response.context["osaps_instance_url"],
            "https://os-aps.sciflow.net/start",
        )

    def test_assignment_view_refuses_another_typesetter(self):
        self.client.force_login(self.other_typesetter)
        response = self.client.get(
            self.url("osaps_typesetting_assignment", assignment_id=self.assignment.pk)
        )

        self.assertNotEqual(response.status_code, 200)

    def test_typesetter_can_complete_their_task(self):
        self.client.force_login(self.typesetter)
        response = self.client.post(
            self.url("osaps_typesetting_assignment", assignment_id=self.assignment.pk),
            {"complete": "1", "typesetter_note": "Exported PDF and HTML."},
        )
        self.assignment.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(self.assignment.completed)
        self.assertEqual(self.assignment.typesetter_note, "Exported PDF and HTML.")

    def test_completing_a_task_does_not_advance_the_stage(self):
        """
        Handing work back to the editor is not the same as completing the
        workflow stage, which is a manager-only action.
        """
        self.client.force_login(self.typesetter)
        self.client.post(
            self.url("osaps_typesetting_assignment", assignment_id=self.assignment.pk),
            {"complete": "1"},
        )
        self.article.refresh_from_db()

        self.assertEqual(self.article.stage, plugin_settings.STAGE)

    def test_completing_an_already_closed_task_is_refused(self):
        self.assignment.completed = timezone.now()
        self.assignment.typesetter_note = "First note."
        self.assignment.save()
        self.client.force_login(self.typesetter)

        response = self.client.post(
            self.url("osaps_typesetting_assignment", assignment_id=self.assignment.pk),
            {"complete": "1", "typesetter_note": "Second note."},
        )
        self.assignment.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.assignment.typesetter_note, "First note.")

    def test_complete_stage_view_advances_the_workflow(self):
        self.client.force_login(self.editor)
        response = self.client.post(
            self.url("osaps_typesetting_complete", article_id=self.article.pk)
        )
        self.article.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.article.stage,
            submission_models.STAGE_READY_FOR_PUBLICATION,
        )

    def test_complete_stage_view_rejects_get(self):
        self.client.force_login(self.editor)
        response = self.client.get(
            self.url("osaps_typesetting_complete", article_id=self.article.pk)
        )

        self.assertEqual(response.status_code, 405)

    def test_complete_stage_view_refuses_a_typesetter(self):
        self.client.force_login(self.typesetter)
        response = self.client.post(
            self.url("osaps_typesetting_complete", article_id=self.article.pk)
        )
        self.article.refresh_from_db()

        self.assertNotEqual(response.status_code, 302)
        self.assertEqual(self.article.stage, plugin_settings.STAGE)

    def test_manager_view_saves_the_instance_url(self):
        self.client.force_login(self.editor)
        response = self.client.post(
            self.url("osaps_typesetting_manager"),
            {"osaps_instance_url": "https://osaps.example.org/saved"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            logic.get_osaps_instance_url(self.journal_one),
            "https://osaps.example.org/saved",
        )

    def test_manager_view_refuses_a_typesetter(self):
        self.client.force_login(self.typesetter)
        response = self.client.get(self.url("osaps_typesetting_manager"))

        self.assertNotEqual(response.status_code, 200)

    def test_manager_view_redirects_anonymous_users(self):
        response = self.client.get(self.url("osaps_typesetting_manager"))

        self.assertEqual(response.status_code, 302)


class TestDownloadFile(OSAPSTestCase):
    """
    The plugin serves its own files because security.logic.can_view_file does
    not know about OSAPSAssignment, so a plugin typesetter is denied by it.
    """

    def test_typesetter_may_download_a_file_from_their_assignment(self):
        temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temp_dir, True)

        with override_settings(BASE_DIR=temp_dir):
            article_dir = os.path.join(
                temp_dir, "files", "articles", str(self.article.pk)
            )
            os.makedirs(article_dir)
            with open(
                os.path.join(article_dir, self.manuscript_file.uuid_filename), "w"
            ) as handle:
                handle.write("manuscript")

            self.client.force_login(self.typesetter)
            response = self.client.get(
                self.url_for_file(self.assignment.pk, self.manuscript_file.pk)
            )

            self.assertEqual(response.status_code, 200)

    def test_a_file_outside_the_assignment_is_404(self):
        self.client.force_login(self.typesetter)
        response = self.client.get(
            self.url_for_file(self.assignment.pk, self.unrelated_file.pk)
        )

        self.assertEqual(response.status_code, 404)

    def test_an_unrelated_user_is_denied(self):
        self.client.force_login(self.unrelated_user)
        response = self.client.get(
            self.url_for_file(self.assignment.pk, self.manuscript_file.pk)
        )

        self.assertNotEqual(response.status_code, 200)

    @staticmethod
    def url_for_file(assignment_id, file_id):
        return reverse(
            "osaps_typesetting_download_file",
            kwargs={"assignment_id": assignment_id, "file_id": file_id},
        )


class TestUploadGalley(OSAPSTestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp_dir, True)

    def upload(self, user, content=b"<html><body>Hi</body></html>", name="export.html"):
        self.client.force_login(user)

        return self.client.post(
            reverse(
                "osaps_typesetting_upload_galley",
                kwargs={"article_id": self.article.pk},
            ),
            {
                "file": SimpleUploadedFile(name, content, content_type="text/html"),
                "label": "HTML",
                "public": True,
            },
        )

    def test_upload_creates_a_galley_and_records_it_on_the_assignment(self):
        with override_settings(BASE_DIR=self.temp_dir):
            response = self.upload(self.typesetter)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.article.galley_set.count(), 1)

        galley = self.article.galley_set.first()

        self.assertIn(galley, self.assignment.galleys_created.all())

    def test_upload_rewrites_absolute_image_sources(self):
        html = (
            b"<html><body>"
            b'<img src="https://os-aps.example.org/asset/doc%2Fmedia%2Fimage1.png">'
            b"</body></html>"
        )

        with override_settings(BASE_DIR=self.temp_dir):
            self.upload(self.typesetter, content=html)
            galley = self.article.galley_set.first()

            with open(galley.file.self_article_path(), encoding="utf-8") as handle:
                content = handle.read()

        self.assertIn('src="image1.png"', content)

    def test_upload_with_no_file_reports_an_error(self):
        self.client.force_login(self.typesetter)

        with override_settings(BASE_DIR=self.temp_dir):
            response = self.client.post(
                reverse(
                    "osaps_typesetting_upload_galley",
                    kwargs={"article_id": self.article.pk},
                ),
                {"label": "HTML"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.article.galley_set.count(), 0)

    def test_upload_refuses_an_unrelated_user(self):
        with override_settings(BASE_DIR=self.temp_dir):
            response = self.upload(self.unrelated_user)

        self.assertNotEqual(response.status_code, 302)
        self.assertEqual(self.article.galley_set.count(), 0)

    def test_upload_rejects_get(self):
        self.client.force_login(self.typesetter)
        response = self.client.get(
            reverse(
                "osaps_typesetting_upload_galley",
                kwargs={"article_id": self.article.pk},
            )
        )

        self.assertEqual(response.status_code, 405)


class TestTemplateTags(OSAPSTestCase):
    def render(self, template, user, journal=None):
        request = self.template_request(user, journal or self.journal_one)

        return Template("{% load osaps_typesetting_tags %}" + template).render(
            Context({"request": request, "article": self.article})
        )

    def test_articles_in_stage_count_tag(self):
        rendered = self.render(
            "{% osaps_articles_in_stage_count %}",
            self.editor,
        )

        self.assertEqual(rendered.strip(), "1")

    def test_open_task_count_tag(self):
        rendered = self.render("{% osaps_open_task_count %}", self.typesetter)

        self.assertEqual(rendered.strip(), "1")

    def test_open_task_count_tag_is_zero_for_others(self):
        rendered = self.render("{% osaps_open_task_count %}", self.editor)

        self.assertEqual(rendered.strip(), "0")

    def test_galley_count_tag(self):
        rendered = self.render(
            "{% osaps_galley_count article %}",
            self.editor,
        )

        self.assertEqual(rendered.strip(), "0")


class TestDashboardElement(OSAPSTestCase):
    """
    The dashboard element decides who sees which button. user_has_role matches
    every role for staff by default, so the typesetter check passes
    staff_override=False and staff are shown the task button only when they
    actually have work. That last branch is the one the manual checks at Step 9
    could not reach without inventing fixture data.
    """

    def render_for(self, user):
        from django.template.loader import render_to_string

        return render_to_string(
            "osaps_typesetting/elements/dashboard.html",
            {"request": self.template_request(user, self.journal_one)},
        )

    def test_editor_sees_the_article_count(self):
        rendered = self.render_for(self.editor)

        self.assertIn("in OS-APS Typesetting", rendered)
        self.assertIn("There is 1 article", " ".join(rendered.split()))

    def test_editor_without_tasks_is_not_told_they_have_none(self):
        rendered = self.render_for(self.editor)

        self.assertNotIn("You have", rendered)

    def test_staff_without_tasks_is_not_told_they_have_none(self):
        rendered = self.render_for(self.staff_user)

        self.assertNotIn("You have", rendered)

    def test_staff_with_an_open_task_sees_the_task_button(self):
        """
        The branch left unverified at Step 9: `typesetter or is_staff and
        num_open_tasks`, with a staff user who does hold an assignment.
        """
        second_round = models.OSAPSRound.objects.create(
            article=self.other_journal_article,
        )
        models.OSAPSAssignment.objects.create(
            round=second_round,
            manager=self.editor,
            typesetter=self.staff_user,
        )
        # The assignment is on journal_two, so it must not count here.
        self.assertNotIn("You have", self.render_for(self.staff_user))

        third_round = models.OSAPSRound.objects.create(
            article=helpers.create_article(
                self.journal_one,
                title="Staff Typesets This",
                stage=plugin_settings.STAGE,
            ),
        )
        models.OSAPSAssignment.objects.create(
            round=third_round,
            manager=self.editor,
            typesetter=self.staff_user,
        )

        rendered = self.render_for(self.staff_user)

        self.assertIn("You have 1 OS-APS Typesetting task", " ".join(rendered.split()))

    def test_typesetter_sees_only_their_task_button(self):
        rendered = " ".join(self.render_for(self.typesetter).split())

        self.assertIn("You have 1 OS-APS Typesetting task", rendered)
        self.assertNotIn("in OS-APS Typesetting</a>", rendered)
        self.assertNotIn("There is", rendered)

    def test_typesetter_with_no_tasks_still_sees_their_button(self):
        self.assignment.completed = timezone.now()
        self.assignment.save()

        rendered = " ".join(self.render_for(self.typesetter).split())

        self.assertIn("You have 0 OS-APS Typesetting tasks", rendered)

    def test_unrelated_user_sees_nothing(self):
        self.assertEqual(self.render_for(self.unrelated_user).strip(), "")
