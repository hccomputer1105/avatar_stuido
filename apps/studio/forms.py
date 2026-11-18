from django import forms
from .models import Avatar, VideoProject


class AvatarForm(forms.ModelForm):
    class Meta:
        model = Avatar
        fields = [
            'name',
            'source_image',
            'visual_style',
            'motion_style',
            'motion_intensity',
            'voice_sample',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. Presentador Caricatura'}),
            'source_image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'visual_style': forms.Select(attrs={'class': 'form-select'}),
            'motion_style': forms.Select(attrs={'class': 'form-select'}),
            'motion_intensity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': '0.3', 'max': '2.0'}),
            'voice_sample': forms.FileInput(attrs={'class': 'form-control', 'accept': 'audio/*'}),
        }


class VideoProjectForm(forms.ModelForm):
    class Meta:
        model = VideoProject
        fields = [
            'avatar',
            'title',
            'voice_mode',
            'voice_id',
            'custom_audio',
            'background_choice',
            'custom_background',
            'script_text',
        ]
        widgets = {
            'avatar': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Título del video'}),
            'voice_mode': forms.Select(attrs={'class': 'form-select', 'id': 'id_voice_mode'}),
            'voice_id': forms.Select(attrs={'class': 'form-select', 'id': 'id_voice_id'}),
            'custom_audio': forms.FileInput(attrs={'class': 'form-control', 'accept': 'audio/*', 'id': 'id_custom_audio'}),
            'background_choice': forms.Select(attrs={'class': 'form-select', 'id': 'id_background_choice'}),
            'custom_background': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'script_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Escribe el guion aquí...'}),
        }

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['avatar'].queryset = Avatar.objects.filter(user=user)
        # Permitir dejar voice_id y script_text opcionales cuando se usa voz clonada o audio subido
        self.fields['voice_id'].required = False
        self.fields['script_text'].required = False

    def clean(self):
        cleaned_data = super().clean()
        mode = cleaned_data.get('voice_mode')
        avatar = cleaned_data.get('avatar')
        voice_id = cleaned_data.get('voice_id')
        custom_audio = cleaned_data.get('custom_audio')
        script_text = cleaned_data.get('script_text')
        bg_choice = cleaned_data.get('background_choice')
        custom_bg = cleaned_data.get('custom_background')

        # Validaciones de voz
        if mode == VideoProject.VoiceMode.SYSTEM:
            if not voice_id:
                self.add_error('voice_id', 'Selecciona una voz del sistema.')
            if not script_text:
                self.add_error('script_text', 'Escribe el guion que leerá la voz del sistema.')

        elif mode == VideoProject.VoiceMode.CLONED:
            if avatar and not avatar.voice_sample:
                self.add_error('voice_mode', 'Este avatar no tiene una muestra de voz guardada. Súbela al crear el avatar.')
            if not script_text:
                self.add_error('script_text', 'Escribe el guion que leerá tu voz clonada.')

        elif mode == VideoProject.VoiceMode.UPLOADED:
            if not custom_audio:
                self.add_error('custom_audio', 'Debes subir un archivo de audio (MP3/WAV) si elegiste esta opción.')

        # Validación de fondo personalizado
        if bg_choice == VideoProject.BackgroundChoice.CUSTOM and not custom_bg:
            self.add_error('custom_background', 'Debes subir una imagen cuando eliges fondo personalizado.')

        return cleaned_data