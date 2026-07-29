from django.db import models


class OSAPSRound(models.Model):
    """One or more rounds of typesetting per article."""

    article = models.ForeignKey(
        "submission.Article",
        on_delete=models.CASCADE,
    )
    round_number = models.IntegerField(default=1)
    date_started = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-round_number"]

    def __str__(self):
        return "Round {0} for {1}".format(self.round_number, self.article)


class OSAPSAssignment(models.Model):
    """
    A typesetting assignment within a round.
    Tracks files-for-typesetting, galleys created, and the OS-APS session.
    """

    round = models.OneToOneField(
        OSAPSRound,
        on_delete=models.CASCADE,
    )
    # Deleting the manager's account must not delete the record of the
    # typesetting work, so the assignment is retained with a null manager.
    manager = models.ForeignKey(
        "core.Account",
        on_delete=models.SET_NULL,
        null=True,
        related_name="osaps_managed_assignments",
    )
    # As above: an assignment outlives the typesetter's account.
    typesetter = models.ForeignKey(
        "core.Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="osaps_typesetting_assignments",
    )
    assigned = models.DateTimeField(auto_now_add=True)
    accepted = models.DateTimeField(null=True, blank=True)
    due = models.DateField(null=True, blank=True)
    completed = models.DateTimeField(null=True, blank=True)
    cancelled = models.DateTimeField(null=True, blank=True)

    # Files flowing into OS-APS
    files_to_typeset = models.ManyToManyField(
        "core.File",
        blank=True,
        related_name="osaps_assignments",
    )

    # Galleys produced in OS-APS and uploaded back
    galleys_created = models.ManyToManyField(
        "core.Galley",
        blank=True,
        related_name="osaps_assignments",
    )

    # Phase 3 hook: stores the OS-APS project URL once API integration is added.
    # Blank in Phase 1. Do not remove this field.
    osaps_project_url = models.URLField(blank=True)

    task = models.TextField(blank=True)
    typesetter_note = models.TextField(blank=True)

    def __str__(self):
        return "Assignment for {0}".format(self.round)
