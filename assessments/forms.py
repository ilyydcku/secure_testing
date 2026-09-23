from django import forms
from django.forms import formset_factory


class TestForm(forms.Form):
    title = forms.CharField(label="Название теста", max_length=255)
    max_attempts = forms.IntegerField(label="Максимальное число попыток", min_value=1, max_value=2147483647, initial=1)


class QuestionForm(forms.Form):
    text = forms.CharField(label="Текст вопроса", widget=forms.Textarea(attrs={"rows": 3}))
    position = forms.IntegerField(label="Позиция вопроса", min_value=1, max_value=2147483647)


class OptionForm(forms.Form):
    id = forms.IntegerField(required=False, widget=forms.HiddenInput, min_value=1)
    text = forms.CharField(label="Текст варианта")
    position = forms.IntegerField(label="Позиция варианта", min_value=1, max_value=2147483647)


OptionFormSet = formset_factory(OptionForm, extra=0)


class AssignmentForm(forms.Form):
    student_id = forms.ChoiceField(label="Студент")

    def __init__(self, *args, students, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student_id"].choices = [(str(s["id"]), s["username"]) for s in students]
