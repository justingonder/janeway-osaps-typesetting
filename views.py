from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.views.decorators.http import require_POST

from core import files, forms as core_forms, models as core_models
from plugins.osaps_typesetting import (
    forms,
    logic,
    models,
    plugin_settings,
    security,
)
from production import logic as production_logic
from security import decorators
from submission import models as submission_models


@decorators.has_journal
@decorators.production_user_or_editor_required
def articles(request):
    """
    Handshake URL. Lists the articles in the OS-APS Typesetting stage.
    :param request: HttpRequest object
    :return: HttpResponse object
    """
    template = "osaps_typesetting/articles.html"
    context = {
        "rows": logic.articles_in_stage(request.journal),
    }

    return render(request, template, context)


@decorators.has_journal
@decorators.production_user_or_editor_required
def article(request, article_id):
    """
    Jump URL. The manager's view of one article's OS-APS typesetting.
    :param request: HttpRequest object
    :param article_id: Article object PK
    :return: HttpResponse object
    """
    article_object = get_object_or_404(
        submission_models.Article,
        pk=article_id,
        journal=request.journal,
    )
    current_round = logic.get_current_round(article_object)

    # Open round one on first view so an editor can start typesetting without
    # first having to assign anyone. Mirrors the core typesetting stage.
    if not current_round:
        logic.new_round(article_object)
        messages.add_message(
            request,
            messages.INFO,
            "New typesetting round created.",
        )

        return redirect(
            reverse(
                "osaps_typesetting_article",
                kwargs={"article_id": article_object.pk},
            )
        )

    template = "osaps_typesetting/article.html"
    context = {
        "article": article_object,
        "round": current_round,
        "assignment": logic.get_assignment(current_round),
        "rounds": article_object.osapsround_set.all(),
        "files": logic.files_for_typesetting(article_object),
        "galleys": core_models.Galley.objects.filter(article=article_object),
        "galley_form": forms.GalleyForm(),
    }

    return render(request, template, context)


@decorators.has_journal
@decorators.production_user_or_editor_required
def assign(request, article_id):
    """
    Assigns a typesetter to the article's current round, or edits the
    existing assignment. Assigning is optional: an editor can typeset an
    article without ever visiting this view.
    :param request: HttpRequest object
    :param article_id: Article object PK
    :return: HttpResponse object
    """
    article_object = get_object_or_404(
        submission_models.Article,
        pk=article_id,
        journal=request.journal,
    )
    current_round = logic.get_current_round(article_object)

    # The jump view opens round one, so send the user there if they have
    # somehow reached this view first.
    if not current_round:
        return redirect(
            reverse(
                "osaps_typesetting_article",
                kwargs={"article_id": article_object.pk},
            )
        )

    assignment = logic.get_assignment(current_round)
    form_kwargs = {
        "instance": assignment,
        "typesetting_round": current_round,
        "manager": request.user,
        "typesetters": request.journal.users_with_role("typesetter"),
        "files": logic.files_for_typesetting(article_object),
    }
    form = forms.AssignmentForm(**form_kwargs)

    if request.POST:
        form = forms.AssignmentForm(request.POST, **form_kwargs)

        if form.is_valid():
            form.save()
            messages.add_message(
                request,
                messages.SUCCESS,
                "Typesetter assigned.",
            )

            return redirect(
                reverse(
                    "osaps_typesetting_article",
                    kwargs={"article_id": article_object.pk},
                )
            )

    template = "osaps_typesetting/assign.html"
    context = {
        "article": article_object,
        "round": current_round,
        "assignment": assignment,
        "form": form,
    }

    return render(request, template, context)


@require_POST
@decorators.has_journal
@decorators.production_user_or_editor_required
def complete(request, article_id):
    """
    Completes the OS-APS typesetting stage for an article and advances the
    workflow to the next element.
    :param request: HttpRequest object
    :param article_id: Article object PK
    :return: HttpResponse object
    """
    article_object = get_object_or_404(
        submission_models.Article,
        pk=article_id,
        journal=request.journal,
        stage=plugin_settings.STAGE,
    )

    response = logic.complete_stage(article_object, request)

    messages.add_message(
        request,
        messages.SUCCESS,
        "OS-APS typesetting completed for {0}.".format(article_object.safe_title),
    )

    return response


@decorators.has_journal
@decorators.typesetter_user_required
def assignments(request):
    """
    Lists the current user's own typesetting tasks. This is how a typesetter
    reaches their work: they have no access to the editor's article views.
    :param request: HttpRequest object
    :return: HttpResponse object
    """
    all_assignments = models.OSAPSAssignment.objects.filter(
        typesetter=request.user,
        round__article__journal=request.journal,
    )

    template = "osaps_typesetting/assignments.html"
    context = {
        "active_assignments": all_assignments.filter(
            completed__isnull=True,
            cancelled__isnull=True,
        ),
        "past_assignments": all_assignments.filter(
            Q(completed__isnull=False) | Q(cancelled__isnull=False),
        ),
    }

    return render(request, template, context)


@decorators.has_journal
@security.typesetter_for_assignment_required
def assignment(request, assignment_id):
    """
    The typesetter's task view: the files to take into OS-APS, a link to the
    configured OS-APS instance, and a form to upload the exported galleys.
    :param request: HttpRequest object
    :param assignment_id: OSAPSAssignment object PK
    :return: HttpResponse object
    """
    assignment_object = get_object_or_404(
        models.OSAPSAssignment,
        pk=assignment_id,
        round__article__journal=request.journal,
    )
    article_object = assignment_object.round.article
    complete_form = forms.CompleteAssignmentForm(instance=assignment_object)

    if request.POST and "complete" in request.POST:
        if assignment_object.completed or assignment_object.cancelled:
            messages.add_message(
                request,
                messages.WARNING,
                "This task is already closed.",
            )
        else:
            complete_form = forms.CompleteAssignmentForm(
                request.POST,
                instance=assignment_object,
            )

            if complete_form.is_valid():
                logic.complete_typesetter_task(
                    assignment_object,
                    note=complete_form.cleaned_data.get("typesetter_note", ""),
                )
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    "Typesetting task marked as complete.",
                )

                return redirect(
                    reverse(
                        "osaps_typesetting_assignment",
                        kwargs={"assignment_id": assignment_object.pk},
                    )
                )

    template = "osaps_typesetting/assignment.html"
    context = {
        "assignment": assignment_object,
        "article": article_object,
        "files": assignment_object.files_to_typeset.all(),
        "galleys": assignment_object.galleys_created.all(),
        "galley_form": forms.GalleyForm(),
        "complete_form": complete_form,
        "osaps_instance_url": logic.get_osaps_instance_url(request.journal),
    }

    return render(request, template, context)


@decorators.has_journal
@security.typesetter_for_assignment_required
def download_file(request, assignment_id, file_id):
    """
    Serves one of the assignment's files to the typesetter. Janeway's own
    article file download denies plugin typesetters, so, as the core
    typesetting stage does, the plugin serves its files itself.
    :param request: HttpRequest object
    :param assignment_id: OSAPSAssignment object PK
    :param file_id: File object PK
    :return: a file response
    """
    assignment_object = get_object_or_404(
        models.OSAPSAssignment,
        pk=assignment_id,
        round__article__journal=request.journal,
    )
    article_object = assignment_object.round.article

    # Only files that are part of this task, or galleys already produced for
    # the article, may be downloaded through this view.
    file_object = get_object_or_404(
        core_models.File,
        pk=file_id,
        article_id=article_object.pk,
    )

    permitted = (
        file_object in assignment_object.files_to_typeset.all()
        or file_object in article_object.data_figure_files.all()
        or file_object.pk
        in article_object.galley_set.values_list("file__pk", flat=True)
    )

    if not permitted:
        raise Http404("File is not part of this typesetting assignment.")

    return files.serve_any_file(
        request,
        file_object,
        path_parts=("articles", article_object.pk),
    )


@decorators.has_journal
@security.typesetter_for_article_required
def edit_galley(request, article_id, galley_id):
    """
    Edits a galley: replace the file, attach the images an HTML or XML galley
    references, attach a stylesheet, or change the label and visibility.

    An HTML galley exported from OS-APS is not publishable until its figures
    are attached, so this view is the other half of the upload step rather
    than an optional extra.
    :param request: HttpRequest object
    :param article_id: Article object PK
    :param galley_id: Galley object PK
    :return: HttpResponse object
    """
    article_object = get_object_or_404(
        submission_models.Article,
        pk=article_id,
        journal=request.journal,
    )
    galley = get_object_or_404(
        core_models.Galley,
        pk=galley_id,
        article=article_object,
    )
    galley_form = forms.GalleyForm(instance=galley, include_file=False)

    if request.POST:
        label = request.POST.get("label")

        if "galley-update" in request.POST:
            galley_form = forms.GalleyForm(
                request.POST,
                instance=galley,
                include_file=False,
            )

            if galley_form.is_valid():
                galley_form.save()
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    "Galley updated.",
                )

        if "replace-galley" in request.POST:
            production_logic.replace_galley_file(
                article_object,
                request,
                galley,
                request.FILES.get("galley"),
            )
            logic.rewrite_remote_image_sources(galley)

        if "fixed-image-upload" in request.POST:
            if request.POST.get("datafile") is not None:
                production_logic.use_data_file_as_galley_image(
                    galley,
                    request,
                    label,
                )
            for uploaded_file in request.FILES.getlist("image"):
                image = production_logic.save_galley_image(
                    galley,
                    request,
                    uploaded_file,
                    label,
                    fixed=True,
                    check_for_existing_images=True,
                )
                # save_galley_image keeps whatever the uploaded file was
                # called, but a galley finds its images by the exact name it
                # references. OS-APS exports reference names like
                # "examplesdocument%2Fmedia%2Fimage1.png", which nobody can
                # reasonably be asked to name a local file, so rename the
                # saved image to the name this slot asked for.
                expected_name = request.POST.get("file_name")
                if image and expected_name:
                    image.original_filename = expected_name
                    image.save()

        if "image-upload" in request.POST:
            for uploaded_file in request.FILES.getlist("image"):
                production_logic.save_galley_image(
                    galley,
                    request,
                    uploaded_file,
                    label,
                    fixed=False,
                    check_for_existing_images=True,
                )

        if "css-upload" in request.POST:
            for uploaded_file in request.FILES.getlist("css"):
                production_logic.save_galley_css(
                    galley,
                    request,
                    uploaded_file,
                    "galley-{0}.css".format(galley.pk),
                    label,
                )

        return redirect(
            reverse(
                "osaps_typesetting_edit_galley",
                kwargs={
                    "article_id": article_object.pk,
                    "galley_id": galley.pk,
                },
            )
        )

    template = "osaps_typesetting/edit_galley.html"
    context = {
        "article": article_object,
        "galley": galley,
        "galley_form": galley_form,
        "galley_images": galley.images.all(),
        "image_names": production_logic.get_image_names(galley),
        "data_files": article_object.data_figure_files.all(),
    }

    return render(request, template, context)


@require_POST
@decorators.has_journal
@security.typesetter_for_article_required
def upload_galley(request, article_id):
    """
    Saves a file exported from OS-APS as a galley and, when the uploader is
    working from an assignment, records it against that assignment.
    :param request: HttpRequest object
    :param article_id: Article object PK
    :return: HttpResponse object
    """
    article_object = get_object_or_404(
        submission_models.Article,
        pk=article_id,
        journal=request.journal,
    )
    current_round = logic.get_current_round(article_object)
    assignment_object = logic.get_assignment(current_round)
    form = forms.GalleyForm(request.POST, request.FILES)
    galley = None

    if form.is_valid():
        try:
            for uploaded_file in request.FILES.getlist("file"):
                galley = logic.create_galley_from_upload(
                    article_object,
                    request,
                    uploaded_file,
                    label=form.cleaned_data.get("label"),
                    public=form.cleaned_data.get("public"),
                )
        except production_logic.ZippedGalleyError:
            messages.add_message(
                request,
                messages.ERROR,
                "You tried to upload a compressed file. Please upload each "
                "exported file separately.",
            )
        except UnicodeDecodeError:
            messages.add_message(
                request,
                messages.ERROR,
                "Uploaded file is not UTF-8 encoded.",
            )
    else:
        messages.add_message(
            request,
            messages.ERROR,
            "No file was uploaded.",
        )

    if galley:
        if assignment_object:
            assignment_object.galleys_created.add(galley)

        messages.add_message(
            request,
            messages.SUCCESS,
            "Galley created from the uploaded file.",
        )

        # An OS-APS HTML export points at assets on the OS-APS server. Point
        # them at local filenames so the figures uploaded here are the ones
        # readers see.
        rewritten = logic.rewrite_remote_image_sources(galley)

        if rewritten:
            messages.add_message(
                request,
                messages.INFO,
                "{0} image reference{1} rewritten to local files. Attach "
                "{2} on the galley's edit page: {3}.".format(
                    len(rewritten),
                    "" if len(rewritten) == 1 else "s",
                    "it" if len(rewritten) == 1 else "them",
                    ", ".join(sorted({name for _, name in rewritten})),
                ),
            )

    if assignment_object and request.user == assignment_object.typesetter:
        return redirect(
            reverse(
                "osaps_typesetting_assignment",
                kwargs={"assignment_id": assignment_object.pk},
            )
        )

    return redirect(
        reverse(
            "osaps_typesetting_article",
            kwargs={"article_id": article_object.pk},
        )
    )


@decorators.has_journal
@decorators.editor_user_required
def manager(request):
    """
    The plugin's settings page, reached from Janeway's plugin manager. Sets
    the OS-APS instance typesetters are sent to for this journal.

    Janeway reverses MANAGER_URL with no arguments (core/views.py:2184), so
    this view takes none; the journal comes from the request.
    :param request: HttpRequest object
    :return: HttpResponse object
    """
    settings, setting_group = logic.get_settings_to_edit(
        request.journal,
        request.user,
    )
    form = core_forms.GeneratedSettingForm(settings=settings)

    if request.POST:
        form = core_forms.GeneratedSettingForm(request.POST, settings=settings)

        if form.is_valid():
            form.save(journal=request.journal, group=setting_group)
            messages.add_message(
                request,
                messages.SUCCESS,
                "OS-APS Typesetting settings saved.",
            )

            return redirect(reverse("osaps_typesetting_manager"))

    template = "osaps_typesetting/manager.html"
    context = {
        "form": form,
        "osaps_instance_url": logic.get_osaps_instance_url(request.journal),
    }

    return render(request, template, context)
