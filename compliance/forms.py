from django import forms

from .models import ComplianceAuditLog


class ResolveFlagForm(forms.Form):
    """Form for the Resolution Action Bar on the Forensic Timeline view."""
    action_taken = forms.ChoiceField(
        choices=ComplianceAuditLog.ACTION_CHOICES,
        widget=forms.RadioSelect,
    )
    manager_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Angela Wang',
        }),
    )
    manager_justification_notes = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Reason for this decision (audited by FSC)',
        }),
        required=True,
        min_length=10,
    )
