from django.db import models
from django.conf import settings


class Avatar(models.Model):
    class VisualStyle(models.TextChoices):
        ORIGINAL = 'original', 'Foto Original'
        CARTOON_3D = 'cartoon_3d', 'Caricatura 3D (Estilo Pixar/Animación)'
        ANIME_2D = 'anime_2d', 'Ilustración 2D / Cómic'

    class MotionStyle(models.TextChoices):
        NATURAL_TALK = 'natural_talk', 'Habla natural (boca y cabeza)'
        EXPRESSIVE = 'expressive', 'Expresivo (boca, cabeza y manos)'
        PRESENTER = 'presenter', 'Presentador corporativo'
        FRIENDLY_SMILE = 'friendly_smile', 'Amigable y sonriente'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='avatars')
    name = models.CharField(max_length=100, verbose_name="Nombre del Avatar")
    source_image = models.ImageField(upload_to='avatars/sources/', verbose_name="Imagen base (Rostro)")
    processed_avatar = models.ImageField(upload_to='avatars/processed/', null=True, blank=True)
    visual_style = models.CharField(
        max_length=20,
        choices=VisualStyle.choices,
        default=VisualStyle.CARTOON_3D,
        verbose_name="Estilo visual"
    )
    motion_style = models.CharField(
        max_length=30,
        choices=MotionStyle.choices,
        default=MotionStyle.EXPRESSIVE,
        verbose_name="Estilo de movimiento"
    )
    motion_intensity = models.FloatField(
        default=1.0,
        help_text="Intensidad del movimiento (0.5 = suave, 1.0 = normal, 1.5 = dinámico)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.user.username})"


class VideoProject(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'En cola'
        PROCESSING = 'PROCESSING', 'Generando animación'
        COMPLETED = 'COMPLETED', 'Completado'
        FAILED = 'FAILED', 'Error'

    class VoiceOption(models.TextChoices):
        ES_FEMALE_1 = 'es-ES-ElviraNeural', 'Español - Voz Femenina (Profesional)'
        ES_MALE_1 = 'es-ES-AlvaroNeural', 'Español - Voz Masculina (Narrador)'
        LATAM_FEMALE = 'es-MX-DaliaNeural', 'Español Latino - Voz Femenina'
        LATAM_MALE = 'es-MX-JorgeNeural', 'Español Latino - Voz Masculino'

    class BackgroundOption(models.TextChoices):
        KEEP_ORIGINAL = 'original', 'Mantener fondo del avatar'
        OFFICE = 'office', 'Oficina Moderna'
        STUDIO = 'studio', 'Estudio de Noticias / Podcast'
        CUSTOM = 'custom', 'Imagen de fondo personalizada'

    class BackgroundChoice(models.TextChoices):
        ORIGINAL = 'original', 'Mantener fondo original'
        GREENSCREEN = 'greenscreen', 'Fondo Verde (Chroma Key)'
        OFFICE = 'office', 'Oficina Moderna'
        STUDIO = 'studio', 'Estudio Profesional'
        CUSTOM = 'custom', 'Imagen personalizada'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='videos')
    avatar = models.ForeignKey(Avatar, on_delete=models.CASCADE, related_name='videos')
    title = models.CharField(max_length=150, verbose_name="Título del video")
    script_text = models.TextField(verbose_name="Guion en texto")
    voice_id = models.CharField(max_length=50, choices=VoiceOption.choices, default=VoiceOption.LATAM_FEMALE)
    background_choice = models.CharField(
        max_length=20,
        choices=BackgroundOption.choices,
        default=BackgroundOption.KEEP_ORIGINAL,
        verbose_name="Fondo del video"
    )
    custom_background = models.ImageField(
        upload_to='videos/backgrounds/',
        null=True,
        blank=True,
        verbose_name="Fondo personalizado (opcional)"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    output_video = models.FileField(upload_to='videos/outputs/', null=True, blank=True)
    external_job_id = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"