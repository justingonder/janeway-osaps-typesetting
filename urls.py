from django.urls import re_path

from plugins.osaps_typesetting import views

urlpatterns = [
    re_path(
        r"^$",
        views.articles,
        name="osaps_typesetting_articles",
    ),
    re_path(
        r"^article/(?P<article_id>\d+)/$",
        views.article,
        name="osaps_typesetting_article",
    ),
    re_path(
        r"^article/(?P<article_id>\d+)/assign/$",
        views.assign,
        name="osaps_typesetting_assign",
    ),
    re_path(
        r"^article/(?P<article_id>\d+)/complete/$",
        views.complete,
        name="osaps_typesetting_complete",
    ),
    re_path(
        r"^article/(?P<article_id>\d+)/galley/(?P<galley_id>\d+)/edit/$",
        views.edit_galley,
        name="osaps_typesetting_edit_galley",
    ),
    re_path(
        r"^article/(?P<article_id>\d+)/galley/upload/$",
        views.upload_galley,
        name="osaps_typesetting_upload_galley",
    ),
    re_path(
        r"^assignments/$",
        views.assignments,
        name="osaps_typesetting_assignments",
    ),
    re_path(
        r"^assignment/(?P<assignment_id>\d+)/$",
        views.assignment,
        name="osaps_typesetting_assignment",
    ),
    re_path(
        r"^assignment/(?P<assignment_id>\d+)/file/(?P<file_id>\d+)/$",
        views.download_file,
        name="osaps_typesetting_download_file",
    ),
    re_path(
        r"^manager/$",
        views.manager,
        name="osaps_typesetting_manager",
    ),
]
