"""
Counts for the dashboard widget and the kanban card.

The dashboard and kanban templates include a plugin's elements with only the
ambient context (and, on the kanban board, `article`), so anything else an
element needs has to come from a tag. Follows
typesetting/templatetags/role_count.py, but the queries themselves live in the
plugin's logic module.

Tag names are prefixed with osaps_ so they cannot be confused with core's
equivalents, which are rendered on the same dashboard page.
"""

from django import template

from plugins.osaps_typesetting import logic

register = template.Library()


@register.simple_tag(takes_context=True)
def osaps_articles_in_stage_count(context):
    """
    The number of articles in the OS-APS typesetting stage on this journal.
    """
    request = context["request"]

    return logic.articles_in_stage_count(request.journal)


@register.simple_tag(takes_context=True)
def osaps_open_task_count(context):
    """
    The number of open OS-APS typesetting tasks assigned to the current user.
    """
    request = context["request"]

    return logic.open_assignment_count(request.user, request.journal)


@register.simple_tag
def osaps_galley_count(article):
    """
    The number of galleys an article has, for the kanban card.
    """
    return article.galley_set.count()
