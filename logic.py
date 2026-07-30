import os
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect, reverse
from django.utils import timezone

from core import (
    files as core_files,
    logic as core_logic,
    models as core_models,
)
from events import logic as event_logic
from plugins.osaps_typesetting import models, plugin_settings
from production import logic as production_logic
from submission import models as submission_models
from utils import setting_handler


def get_current_round(article):
    """
    Returns the most recent round for an article, or None.
    OSAPSRound orders by -round_number, so first() is the current round.
    :param article: an Article object
    :return: an OSAPSRound object or None
    """
    return models.OSAPSRound.objects.filter(article=article).first()


def new_round(article):
    """
    Opens a new round for an article, numbered one above the current round.
    :param article: an Article object
    :return: an OSAPSRound object
    """
    current_round = get_current_round(article)
    round_number = current_round.round_number + 1 if current_round else 1

    return models.OSAPSRound.objects.create(
        article=article,
        round_number=round_number,
    )


def get_assignment(typesetting_round):
    """
    Returns the assignment for a round, or None if no one has been assigned yet.
    :param typesetting_round: an OSAPSRound object
    :return: an OSAPSAssignment object or None
    """
    if not typesetting_round:
        return None

    return getattr(typesetting_round, "osapsassignment", None)


def files_for_typesetting(article):
    """
    Gathers the files a typesetter may need to take into OS-APS: the
    manuscript files, any copyedited files and any figures or data files.
    :param article: an Article object
    :return: a queryset of File objects
    """
    query = Q(manuscript_files=article)
    query |= Q(data_figure_files=article)
    query |= Q(copyeditor_files__article=article)

    return core_models.File.objects.filter(query).distinct()


def articles_in_stage(journal):
    """
    Articles in the OS-APS typesetting stage, each with the round, assignment
    and galley count the list view needs, so the template does not have to
    walk relationships itself.
    :param journal: a Journal object
    :return: list of dicts
    """
    articles = submission_models.Article.objects.filter(
        journal=journal,
        stage=plugin_settings.STAGE,
    )
    rows = []

    for article in articles:
        current_round = get_current_round(article)
        rows.append(
            {
                "article": article,
                "round": current_round,
                "assignment": get_assignment(current_round),
                "galley_count": article.galley_set.count(),
            }
        )

    return rows


def articles_in_stage_count(journal):
    """
    How many of a journal's articles are in the OS-APS typesetting stage.
    Counted in the database rather than by len(articles_in_stage()), which
    walks every article's rounds and galleys.
    :param journal: a Journal object
    :return: int
    """
    return submission_models.Article.objects.filter(
        journal=journal,
        stage=plugin_settings.STAGE,
    ).count()


def open_assignment_count(user, journal):
    """
    How many OS-APS typesetting tasks a user has open on a journal. Matches
    the "active" list in views.assignments.
    :param user: an Account object
    :param journal: a Journal object
    :return: int
    """
    if not user or not user.is_authenticated:
        return 0

    return models.OSAPSAssignment.objects.filter(
        typesetter=user,
        round__article__journal=journal,
        completed__isnull=True,
        cancelled__isnull=True,
    ).count()


def get_osaps_instance_url(journal):
    """
    Returns the configured OS-APS instance URL for a journal, falling back to
    the plugin default installed by install/settings.json.
    :param journal: a Journal object
    :return: string
    """
    setting = setting_handler.get_setting(
        plugin_settings.SETTING_GROUP_NAME,
        "osaps_instance_url",
        journal,
    )

    return setting.processed_value if setting else ""


def get_settings_to_edit(journal, user):
    """
    The plugin's journal settings in the shape core.forms.GeneratedSettingForm
    expects, dropping any the user is not permitted to edit. Follows
    core.logic.get_settings_to_edit, which does the same for core's own
    setting groups.
    :param journal: a Journal object
    :param user: an Account object
    :return: (list of dicts, setting group name)
    """
    settings = [
        {
            "name": "osaps_instance_url",
            "object": setting_handler.get_setting(
                plugin_settings.SETTING_GROUP_NAME,
                "osaps_instance_url",
                journal,
            ),
        },
    ]
    editable = [
        setting
        for setting in settings
        if core_logic.user_can_edit_setting(
            setting=setting["object"],
            user=user,
            journal=journal,
        )
    ]

    return editable, plugin_settings.SETTING_GROUP_NAME


def create_galley_from_upload(article, request, uploaded_file, label=None, public=True):
    """
    Saves a file exported from OS-APS as a galley. Wraps
    production.logic.save_galley so file handling is not reimplemented here.
    :param article: an Article object
    :param request: HttpRequest object
    :param uploaded_file: an UploadedFile object
    :param label: optional galley label; Janeway derives one when omitted
    :param public: whether the galley is publicly visible
    :return: a Galley object
    """
    return production_logic.save_galley(
        article=article,
        request=request,
        uploaded_file=uploaded_file,
        is_galley=True,
        label=label,
        public=public,
    )


def complete_stage(article, request):
    """
    Closes OS-APS typesetting for an article and hands over to the next
    workflow element.

    SPEC.md describes this as complete_assignment(assignment, request), but an
    article can reach this point with no assignment at all — an editor may have
    done the typesetting themselves — so it is keyed on the article. Any open
    assignment is closed on the way through.
    :param article: an Article object
    :param request: HttpRequest object
    :return: HttpResponse object
    """
    current_round = get_current_round(article)
    assignment = get_assignment(current_round)

    if assignment and not assignment.completed and not assignment.cancelled:
        assignment.completed = timezone.now()
        assignment.save()

    if not request.journal.element_in_workflow(
        element_name=plugin_settings.PLUGIN_NAME,
    ):
        messages.add_message(
            request,
            messages.WARNING,
            "OS-APS Typesetting is not part of this journal's workflow, so "
            "the article could not be moved to the next stage.",
        )

        return redirect(reverse("core_dashboard"))

    return event_logic.Events.raise_event(
        event_logic.Events.ON_WORKFLOW_ELEMENT_COMPLETE,
        task_object=article,
        handshake_url=plugin_settings.HANDSHAKE_URL,
        request=request,
        article=article,
        switch_stage=True,
    )


# The elements Janeway itself scans for figures, see Galley.has_missing_image_files
IMAGE_ELEMENTS = {
    "img": "src",
    "graphic": "xlink:href",
    "inline-graphic": "xlink:href",
}


def rewrite_remote_image_sources(galley):
    """
    Points a galley's image references at local filenames.

    OS-APS exports reference their assets by absolute URL on the OS-APS
    server, e.g.

        <img src="https://os-aps.sciflow.net/export/asset/<slug>/doc%2Fmedia%2Fimage1.png">

    Left alone, a published article would load its figures from that server,
    which may be a demo instance and whose URLs look session-scoped. Janeway
    also matches attached images on os.path.basename() of the reference, so the
    galley would expect a file named "doc%2Fmedia%2Fimage1.png".

    This rewrites any absolute http(s) reference to the decoded final path
    segment ("image1.png"), so an image attached under that name renders.
    Relative references and data URIs are left alone.
    :param galley: a Galley object
    :return: list of (original_reference, local_name) tuples that were changed
    """
    if not galley.file or galley.file.mime_type not in core_files.HTML_MIMETYPES:
        return []

    path = galley.file.self_article_path()
    rewritten = []

    with open(path, "r+", encoding="utf-8") as galley_file:
        soup = BeautifulSoup(galley_file.read(), "html.parser")

        for element, attribute in IMAGE_ELEMENTS.items():
            for tag in soup.find_all(element):
                reference = tag.get(attribute)

                if not reference:
                    continue

                parsed = urlparse(reference)

                if parsed.scheme not in ("http", "https"):
                    continue

                local_name = os.path.basename(unquote(parsed.path))

                if local_name:
                    tag[attribute] = local_name
                    rewritten.append((reference, local_name))

        if rewritten:
            galley_file.seek(0)
            galley_file.write(str(soup))
            galley_file.truncate()

    return rewritten


def complete_typesetter_task(assignment, note=""):
    """
    Marks the typesetter's task complete. This hands the work back to the
    editor; completing the workflow stage itself is a separate, manager-only
    action.
    :param assignment: an OSAPSAssignment object
    :param note: optional note from the typesetter
    :return: the OSAPSAssignment object
    """
    assignment.completed = timezone.now()
    assignment.typesetter_note = note
    assignment.save()

    return assignment
