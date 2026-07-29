from functools import wraps

from django.shortcuts import redirect, reverse

from plugins.osaps_typesetting import models
from security.decorators import base_check, deny_access


def _user_is_manager(request):
    """
    Editors, staff and production users can always reach the typesetting
    views, whether or not they are assigned to the article.
    """
    return (
        request.user.is_editor(request)
        or request.user.is_staff
        or request.user.is_production(request)
    )


def typesetter_for_assignment_required(func):
    """
    Checks that the current user is the typesetter for this assignment, or a
    manager. Follows typesetting.security.proofreader_for_article_required.
    :param func: the function to callback from the decorator
    :return: either the function call or denies access
    """

    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if not base_check(request):
            return redirect(
                "{0}?next={1}".format(
                    reverse("core_login"),
                    request.path,
                )
            )

        elif _user_is_manager(request):
            return func(request, *args, **kwargs)

        # User is assigned as the typesetter, regardless of role
        elif models.OSAPSAssignment.objects.filter(
            pk=kwargs["assignment_id"],
            typesetter=request.user,
            cancelled__isnull=True,
            round__article__journal=request.journal,
        ).exists():
            return func(request, *args, **kwargs)

        else:
            deny_access(request)

    return wrapper


def typesetter_for_article_required(func):
    """
    As above, but for views keyed on an article rather than an assignment:
    the user must be the typesetter on one of the article's assignments.
    :param func: the function to callback from the decorator
    :return: either the function call or denies access
    """

    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if not base_check(request):
            return redirect(
                "{0}?next={1}".format(
                    reverse("core_login"),
                    request.path,
                )
            )

        elif _user_is_manager(request):
            return func(request, *args, **kwargs)

        elif models.OSAPSAssignment.objects.filter(
            round__article__pk=kwargs["article_id"],
            round__article__journal=request.journal,
            typesetter=request.user,
            cancelled__isnull=True,
        ).exists():
            return func(request, *args, **kwargs)

        else:
            deny_access(request)

    return wrapper
