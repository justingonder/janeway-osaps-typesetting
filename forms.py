from django import forms

from core import models as core_models
from plugins.osaps_typesetting import models
from utils.forms import HTMLDateInput


class AssignmentForm(forms.ModelForm):
    """
    Creates or edits the typesetting assignment for a round.

    The manager and the round are set from the view rather than exposed as
    fields: the manager is always the user doing the assigning, and the round
    is always the article's current round.
    """

    def __init__(self, *args, **kwargs):
        self.typesetting_round = kwargs.pop("typesetting_round")
        self.manager = kwargs.pop("manager")
        typesetters = kwargs.pop("typesetters")
        files = kwargs.pop("files")
        super().__init__(*args, **kwargs)

        self.fields["typesetter"].queryset = typesetters
        self.fields["typesetter"].required = True
        self.fields["files_to_typeset"].queryset = files

    class Meta:
        model = models.OSAPSAssignment
        fields = (
            "typesetter",
            "due",
            "task",
            "files_to_typeset",
        )
        widgets = {
            # Native HTML5 date input, no JavaScript date picker.
            "due": HTMLDateInput(),
            "files_to_typeset": forms.CheckboxSelectMultiple(),
        }
        labels = {
            "due": "Due date",
            "task": "Notes for the typesetter",
            "files_to_typeset": "Files to send for typesetting",
        }

    def save(self, commit=True):
        assignment = super().save(commit=False)
        assignment.round = self.typesetting_round

        # Record who made the assignment, but leave the original manager in
        # place when an existing assignment is being edited.
        if not assignment.manager:
            assignment.manager = self.manager

        if commit:
            assignment.save()
            self.save_m2m()

        return assignment


class GalleyForm(forms.ModelForm):
    """
    Uploads a file exported from OS-APS as a galley. Standard file input,
    no JavaScript uploader.
    """

    file = forms.FileField(
        label="File exported from OS-APS",
    )

    class Meta:
        model = core_models.Galley
        fields = (
            "label",
            "public",
        )

    def __init__(self, *args, **kwargs):
        # The edit view reuses this form for label and visibility only.
        include_file = kwargs.pop("include_file", True)
        super().__init__(*args, **kwargs)
        # Janeway works the label out from the file type when none is given.
        self.fields["label"].required = False

        if not include_file:
            self.fields.pop("file")


class CompleteAssignmentForm(forms.ModelForm):
    """
    Lets the typesetter hand the work back with a note.
    """

    class Meta:
        model = models.OSAPSAssignment
        fields = ("typesetter_note",)
        labels = {
            "typesetter_note": "Note for the editor (optional)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["typesetter_note"].required = False
