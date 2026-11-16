from django import forms
from .models import Avatar, VideoProject


class AvatarForm(forms.ModelForm):
    class Meta:
        model = Avatar
        fields = ['name', 'source_image', 'visual_style', 'motion_style', 'motion_intensity']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. Presentador Caricatura'}),
            'source_image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'visual_style': forms.Select(attrs={'class': 'form-select'}),
            'motion_style': forms.Select(attrs={'class': 'form-select'}),
            'motion_intensity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': '0.3', 'max': '2.0'}),
        }


class VideoProjectForm(forms.ModelForm):
    class Meta:
        model = VideoProject
        fields = ['avatar', 'title', 'voice_id', 'background_choice', 'custom_background', 'script_text']
        widgets = {
            'avatar': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Título del video'}),
            'voice_id': forms.Select(attrs={'class': 'form-select'}),
            'background_choice': forms.Select(attrs={'class': 'form-select'}),
            'custom_background': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'script_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Escribe el guion aquí...'}),
        }

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['avatar'].queryset = Avatar.objects.filter(user=user)