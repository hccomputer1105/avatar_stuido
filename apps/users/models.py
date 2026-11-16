from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrador'
        CREATOR = 'CREATOR', 'Creador de Contenido'
        REVIEWER = 'REVIEWER', 'Revisor / Cliente'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CREATOR,
        verbose_name="Rol del sistema"
    )
    video_credits = models.PositiveIntegerField(
        default=5,
        verbose_name="Créditos de video disponibles"
    )

    def is_admin_role(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    def is_creator_role(self):
        return self.role == self.Role.CREATOR
